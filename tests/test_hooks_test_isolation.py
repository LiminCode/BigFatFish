# -*- coding: utf-8 -*-
"""测试里绝不碰这台机器真实的 ``~/.claude/settings.json``（conftest 的总夹具把路径指到临时目录）。

2026-11-20 凌晨：真壳的用例把 claude 联动关掉 → ``_uninstall_hooks`` → 改写了开发机上真实的 settings.json，本机 hooks 被清光。
"""
from __future__ import annotations

from pathlib import Path

from pet.agent_link import AgentLinkManager, ClaudeCodeMonitor
from pet.config import Config


def test_the_settings_path_points_into_the_temp_dir_under_pytest(tmp_path):
    path = ClaudeCodeMonitor.get_settings_path()
    assert tmp_path in path.parents, "conftest 把 settings.json 指到了每个用例自己的临时目录"
    assert path != Path.home() / ".claude" / "settings.json"


def test_turning_the_claude_link_off_writes_only_the_temp_settings_file(tmp_path):
    settings = ClaudeCodeMonitor.get_settings_path()
    settings.parent.mkdir(parents=True)
    settings.write_text('{"hooks": {}}', encoding="utf-8")
    real = Path.home() / ".claude" / "settings.json"
    before = real.stat().st_mtime_ns if real.is_file() else None

    class Win:
        def isVisible(self):
            return True

        def mark_activity(self):
            pass

        def show_bubble(self, *_a, **_k):
            pass

    config = Config(base=tmp_path)
    config.set("agent_link", {**config.get("agent_link"), "claude": True})
    mgr = AgentLinkManager(Win(), config, min_interval=0.0)
    mgr.apply_config()
    assert mgr.monitors["claude"]._running
    config.set("agent_link", {**config.get("agent_link"), "claude": False})
    mgr.apply_config()                               # 在跑 → 停：走卸 hooks 那条路
    assert not mgr.monitors["claude"]._running
    assert (real.stat().st_mtime_ns if real.is_file() else None) == before, "真实的 settings.json 一个字节都不许动"
