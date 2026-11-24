# -*- coding: utf-8 -*-
"""个人助理的纯逻辑：配置、Windows git 的提交 / 推送序列与 Token 注入、Obsidian 地址（随手记落盘见 test_capture_inbox）。

纪律：不起真的 git.exe、不碰真实克隆、不发网络请求——git 用假运行器，Token 的 scopes 用假 opener。
样例文字全是中性的。
"""
from __future__ import annotations

import base64
import datetime as dt
import os
from pathlib import Path

import pytest

from pet import personal_vault as pv
from pet.config import Config

NOW = dt.datetime(2026, 10, 17, 9, 5)


# ---------------------------------------------------------------- 配置

def test_defaults_are_off_and_point_at_the_github_clone(tmp_path):
    settings = Config(tmp_path).get(pv.CONFIG_KEY)
    assert settings == {"enabled": False, "repo_dir": pv.default_repo_dir(), "time": "08:30", "model": "", "effort": ""}
    assert pv.default_repo_dir().endswith(os.path.join("Github", "AI-Base"))


def test_bad_values_are_cleaned_and_good_ones_survive_a_restart(tmp_path):
    config = Config(tmp_path)
    config.set(pv.CONFIG_KEY, {"enabled": True, "repo_dir": r"D:\vault", "time": "7:05", "model": "claude-haiku-5-5",
                               "effort": "HIGH"})
    config.save()
    assert Config(tmp_path).get(pv.CONFIG_KEY) == {"enabled": True, "repo_dir": r"D:\vault", "time": "07:05",
                                                   "model": "claude-haiku-5-5", "effort": "high"}
    config.set(pv.CONFIG_KEY, {"enabled": "yes", "time": "25:99", "model": "sonnet; rm -rf ~", "effort": "ultra"})
    config.save()
    cleaned = Config(tmp_path).get(pv.CONFIG_KEY)
    assert cleaned["enabled"] is False and cleaned["time"] == "08:30"
    assert cleaned["model"] == "" and cleaned["effort"] == "", "认不出来的模型 / 强度退回「跟聊天一致」"


# ---------------------------------------------------------------- git

class _Git:
    """假 git：记下每次的参数与环境，按脚本返回。"""

    def __init__(self, results: dict | None = None):
        self.calls: list[tuple[tuple[str, ...], dict | None, float | None]] = []
        self.results = results or {}

    def __call__(self, repo_dir, args, *, timeout=None, env=None):
        self.calls.append((tuple(args), env, timeout))
        return self.results.get(args[0], (0, ""))

    @property
    def commands(self) -> list[str]:
        return [" ".join(call[0][:2]) for call in self.calls]


def test_sync_adds_commits_pulls_and_pushes_with_the_token_in_the_environment(tmp_path):
    git = _Git({"diff": (1, "")})
    ok, reason = pv.sync_path(tmp_path, ["0-Inbox/a.md", "0-Inbox/assets/a-1.png"], "capture: 2026-10-17 09:05", run=git, token="ghp_example")
    assert ok and reason == ""
    assert git.commands == ["add --", "diff --cached", "commit -q", "pull -q", "push -q"]
    add_args, commit_args = git.calls[0][0], git.calls[2][0]
    assert add_args[1:] == ("--", "0-Inbox/a.md", "0-Inbox/assets/a-1.png"), "几个文件一次 add"
    assert commit_args[-1] == "capture: 2026-10-17 09:05", "提交说明不含正文"
    pull_env, push_env = git.calls[3][1], git.calls[4][1]
    assert pull_env == push_env and push_env["GIT_CONFIG_VALUE_0"] == "" and "ghp_example" not in str(git.calls[4][0])
    expected = base64.b64encode(b"x-access-token:ghp_example").decode()
    assert push_env["GIT_CONFIG_VALUE_1"] == f"Authorization: Basic {expected}"
    assert git.calls[0][1] is None, "本地命令不带 Token"


def test_nothing_staged_means_no_commit_but_still_a_push(tmp_path):
    git = _Git({"diff": (0, "")})
    assert pv.sync_path(tmp_path, ["0-Inbox/a.md", "0-Inbox/assets/a-1.png"], "capture: 2026-10-17 09:05", run=git) == (True, "")
    assert git.commands == ["add --", "diff --cached", "pull -q", "push -q"]
    assert git.calls[-1][1] is None and git.calls[-1][2] == pv.FIRST_PUSH_TIMEOUT_S, "没有 Token 时交给凭据管理器，给足时间"


def test_a_failed_pull_is_aborted_and_reported(tmp_path):
    git = _Git({"diff": (1, ""), "pull": (1, "CONFLICT (content): Merge conflict in User/x.md")})
    ok, reason = pv.sync_path(tmp_path, ["0-Inbox/a.md", "0-Inbox/assets/a-1.png"], "capture: 2026-10-17 09:05", run=git)
    assert not ok and "CONFLICT" in reason
    assert git.commands == ["add --", "diff --cached", "commit -q", "pull -q", "rebase --abort"]


def test_a_rejected_token_falls_back_to_plain_git_once_and_names_the_scopes(tmp_path):
    class _Push(_Git):
        def __call__(self, repo_dir, args, *, timeout=None, env=None):
            self.calls.append((tuple(args), env, timeout))
            if args[0] == "push":
                return (1, "remote: Permission to x/y denied. fatal: 403") if env else (1, "still no")
            return (1, "") if args[0] == "diff" else (0, "")

    git = _Push()
    ok, reason = pv.sync_path(tmp_path, ["0-Inbox/a.md", "0-Inbox/assets/a-1.png"], "capture: 2026-10-17 09:05", run=git, token="ghp_x")
    assert not ok and "[token scopes: " in reason
    pushes = [call for call in git.calls if call[0][0] == "push"]
    assert len(pushes) == 2 and pushes[0][1] and pushes[1][1] is None and pushes[1][2] == pv.FIRST_PUSH_TIMEOUT_S


def test_fetch_only_asks_the_remote_and_does_not_wait_as_long_as_a_push(tmp_path):
    git = _Git()
    assert pv.fetch(tmp_path, run=git, token="ghp_example") == (True, "")
    (args, env, timeout), = git.calls
    assert args == ("fetch", "-q") and timeout == pv.FETCH_TIMEOUT_S, "不 pull、不 rebase：工作区和本地分支都不动"
    assert env["GIT_CONFIG_VALUE_1"].startswith("Authorization: Basic ") and "ghp_example" not in str(args)
    offline = _Git({"fetch": (128, "fatal: unable to access 'https://github.com/acme/handbook.git/': Could not resolve host")})
    ok, reason = pv.fetch(tmp_path, run=offline)
    assert not ok and "Could not resolve host" in reason
    assert offline.calls[-1][2] == pv.FETCH_TIMEOUT_S, "没有 Token 时交给凭据管理器，也只等这么久（有人在页面上等）"


def test_upstream_state_says_where_the_remote_branch_points_and_how_far_apart_they_are(tmp_path):
    git = _Git({"rev-parse": (0, "5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e\n"), "rev-list": (0, "46\t2\n")})
    assert pv.upstream_state(tmp_path, run=git) == {"head": "5d6e7f8a9b0c", "behind": 46, "ahead": 2}
    assert [call[0] for call in git.calls] == [("rev-parse", "@{upstream}"), ("rev-list", "--left-right", "--count", "@{upstream}...HEAD")]
    assert all(call[1] is None for call in git.calls), "两条都是本地命令：不带 Token、不联网"
    no_upstream = _Git({"rev-parse": (128, "fatal: no upstream configured"), "rev-list": (128, "fatal")})
    assert pv.upstream_state(tmp_path, run=no_upstream) == {"head": "", "behind": None, "ahead": None}, "问不出来 ≠ 没有差距"


def test_token_scopes_come_from_the_github_header(monkeypatch):
    class _Response:
        headers = {"X-OAuth-Scopes": "repo, read:user"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    assert pv.describe_token_scopes("ghp_x", opener=lambda req, timeout: _Response()) == "repo, read:user"
    _Response.headers = {}
    assert pv.describe_token_scopes("ghp_x", opener=lambda req, timeout: _Response()) == "fine-grained"

    def boom(req, timeout):
        raise OSError("offline")

    assert pv.describe_token_scopes("ghp_x", opener=boom) == "" and pv.describe_token_scopes("") == ""


def test_git_exe_falls_back_to_the_default_install(monkeypatch):
    monkeypatch.setattr(pv.sys, "platform", "win32")
    monkeypatch.setattr(pv.shutil, "which", lambda name: None)
    monkeypatch.setattr(Path, "exists", lambda self: str(self) == pv.GIT_FALLBACK)
    assert pv.git_exe() == pv.GIT_FALLBACK
    monkeypatch.setattr(Path, "exists", lambda self: False)
    assert pv.git_exe() is None
    assert pv.run_git(r"C:\nowhere", ["status"]) == (127, "")


# ---------------------------------------------------------------- Obsidian

def test_obsidian_uri_uses_the_path_form_only_when_the_clone_is_registered(tmp_path):
    clone = tmp_path / "AI-Base"
    clone.mkdir()
    (clone / "INDEX.md").write_text("# map\n", encoding="utf-8")
    vaults = {"a": {"path": "G:\\My Drive\\AI-Base"}, "b": {"path": str(clone).upper()}}
    uri = pv.obsidian_vault_uri(clone, vaults)
    assert uri.startswith("obsidian://open?path=") and "vault=" not in uri, "同名的 Drive 旧库会被 vault= 撞上"
    assert uri.endswith("INDEX.md".replace("/", "%2F")) and "%5C" in uri or "%2F" in uri
    assert pv.obsidian_vault_uri(clone, {"a": {"path": "G:\\My Drive\\AI-Base"}}) == ""


@pytest.mark.parametrize("value, expected", [("medium", "medium"), (" XHIGH ", "xhigh"), ("", ""), ("turbo", "")])
def test_effort_levels_are_normalised(value, expected):
    assert pv.normalize_effort(value) == expected
