# -*- coding: utf-8 -*-
"""个人助理的纯逻辑：配置、灵感追加、Windows git 的提交 / 推送序列与 Token 注入、Obsidian 地址。

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
LATER = dt.datetime(2026, 10, 17, 21, 40)
TOMORROW = dt.datetime(2026, 10, 18, 8, 0)


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


# ---------------------------------------------------------------- 灵感追加

def test_the_first_idea_creates_the_file_with_frontmatter_and_todays_section(tmp_path):
    path = pv.append_inspiration(tmp_path, "把阳台的灯换成感应的", NOW)
    assert path == tmp_path / "User" / "灵感 Inspiration.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: 灵感 Inspiration\n") and "created: 2026-10-17\nupdated: 2026-10-17\n" in text
    assert "# 灵感 Inspiration" in text
    assert text.endswith("## 2026-10-17\n\n- 09:05 把阳台的灯换成感应的\n")
    assert "\r" not in text


def test_later_ideas_join_todays_section_and_a_new_day_opens_a_new_one(tmp_path):
    pv.append_inspiration(tmp_path, "第一条", NOW)
    pv.append_inspiration(tmp_path, "第二条\n第二行细节", LATER)
    text = pv.inspiration_path(tmp_path).read_text(encoding="utf-8")
    assert text.endswith("## 2026-10-17\n\n- 09:05 第一条\n- 21:40 第二条\n  第二行细节\n"), "同一天追加在同一节，多行缩进两格"
    pv.append_inspiration(tmp_path, "次日", TOMORROW)
    text = pv.inspiration_path(tmp_path).read_text(encoding="utf-8")
    assert text.endswith("- 21:40 第二条\n  第二行细节\n\n## 2026-10-18\n\n- 08:00 次日\n")
    assert text.count("updated: 2026-10-18") == 1 and "updated: 2026-10-17" not in text


def test_appending_into_the_middle_section_keeps_what_follows(tmp_path):
    path = pv.inspiration_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("---\ntitle: x\nupdated: 2026-10-16\n---\n\n## 2026-10-17\n\n- 08:00 早的\n\n## 2026-10-16\n\n- 10:00 昨天的\n",
                    encoding="utf-8")
    pv.append_inspiration(tmp_path, "插进今天", NOW)
    text = path.read_text(encoding="utf-8")
    assert "## 2026-10-17\n\n- 08:00 早的\n- 09:05 插进今天\n\n## 2026-10-16\n\n- 10:00 昨天的\n" in text
    assert "updated: 2026-10-17" in text


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
    ok, reason = pv.sync_inspiration(tmp_path, NOW, run=git, token="ghp_example")
    assert ok and reason == ""
    assert git.commands == ["add --", "diff --cached", "commit -q", "pull -q", "push -q"]
    add_args, commit_args = git.calls[0][0], git.calls[2][0]
    assert add_args[-1] == pv.INSPIRATION_FILE and commit_args[-1] == "inspiration: 2026-10-17 09:05", "提交说明不含正文"
    pull_env, push_env = git.calls[3][1], git.calls[4][1]
    assert pull_env == push_env and push_env["GIT_CONFIG_VALUE_0"] == "" and "ghp_example" not in str(git.calls[4][0])
    expected = base64.b64encode(b"x-access-token:ghp_example").decode()
    assert push_env["GIT_CONFIG_VALUE_1"] == f"Authorization: Basic {expected}"
    assert git.calls[0][1] is None, "本地命令不带 Token"


def test_nothing_staged_means_no_commit_but_still_a_push(tmp_path):
    git = _Git({"diff": (0, "")})
    assert pv.sync_inspiration(tmp_path, NOW, run=git) == (True, "")
    assert git.commands == ["add --", "diff --cached", "pull -q", "push -q"]
    assert git.calls[-1][1] is None and git.calls[-1][2] == pv.FIRST_PUSH_TIMEOUT_S, "没有 Token 时交给凭据管理器，给足时间"


def test_a_failed_pull_is_aborted_and_reported(tmp_path):
    git = _Git({"diff": (1, ""), "pull": (1, "CONFLICT (content): Merge conflict in User/x.md")})
    ok, reason = pv.sync_inspiration(tmp_path, NOW, run=git)
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
    ok, reason = pv.sync_inspiration(tmp_path, NOW, run=git, token="ghp_x")
    assert not ok and "[token scopes: " in reason
    pushes = [call for call in git.calls if call[0][0] == "push"]
    assert len(pushes) == 2 and pushes[0][1] and pushes[1][1] is None and pushes[1][2] == pv.FIRST_PUSH_TIMEOUT_S


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
