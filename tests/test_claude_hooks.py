# -*- coding: utf-8 -*-
"""pet/claude_hooks.py：Claude Code hooks 接入的纯逻辑层。

hook 脚本用**真实 shell 进程**测（Windows 走 Git Bash，其余平台走 /bin/sh）——
脚本的正确性就是 shell 语义本身，桩掉 shell 等于什么都没测。载荷形状取自
2026-10-10 实机抓到的 Claude Code 2.1.295 hook stdin（单行紧凑 JSON、字段顺序如实）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pet import claude_hooks as ch
from pet.claude_hooks import ClaudeSessionTracker


# ---------------------------------------------------------------- hook 脚本（真实 shell）

def _shell() -> str | None:
    if sys.platform == "win32":
        return ch.find_git_bash()
    return shutil.which("sh")


def _payload(event: str, *, session: str = "e0a4f9a8-e0da-4be1-8b25-839ee25b8372", **extra) -> str:
    """按 Claude Code 实际字段顺序拼一行 hook stdin。"""
    body = {
        "session_id": session,
        "transcript_path": "C:\\Users\\me\\.claude\\projects\\p\\t.jsonl",
        "cwd": "C:\\Users\\me\\secret-project",
        "hook_event_name": event,
    }
    body.update(extra)
    return json.dumps(body, separators=(",", ":")) + "\n"


def _run_hook(tmp_path: Path, event: str, stdin: str, *, agent: str = "claude") -> list[dict]:
    shell = _shell()
    if shell is None:
        pytest.skip("本机没有可用的 sh / Git Bash")
    script = tmp_path / ch.HOOK_SCRIPT_NAME
    ch.write_hook_script(script)
    out = tmp_path / f"{agent}.jsonl"
    command = ch.sh_hook_command(script.as_posix(), out.as_posix(), agent, event)
    proc = subprocess.run([shell, "-c", command], input=stdin.encode("utf-8"),
                          capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    if not out.exists():
        return []
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]


def test_hook_script_is_written_with_lf_line_endings(tmp_path):
    """CRLF 会让 dash 把 ``\\r`` 当成命令的一部分——WSL 里整个脚本就废了。"""
    script = tmp_path / ch.HOOK_SCRIPT_NAME
    ch.write_hook_script(script)
    assert b"\r" not in script.read_bytes()


def test_hook_records_session_and_tool_but_no_content(tmp_path):
    stdin = _payload("PreToolUse", tool_name="Bash",
                     tool_input={"command": "cat ~/.ssh/id_rsa"}, tool_use_id="toolu_1")
    records = _run_hook(tmp_path, "PreToolUse", stdin)

    assert len(records) == 1
    rec = records[0]
    assert rec["event"] == "PreToolUse" and rec["agent"] == "claude"
    assert rec["sessionId"] == "e0a4f9a8-e0da-4be1-8b25-839ee25b8372"
    assert rec["tool"] == "Bash"
    assert isinstance(rec["ts"], (int, float)) and rec["ts"] > 1_600_000_000
    assert set(rec) == {"ts", "agent", "event", "sessionId", "tool"}, "只许落元数据"
    raw = (tmp_path / "claude.jsonl").read_text(encoding="utf-8")
    assert "id_rsa" not in raw and "secret-project" not in raw


def test_hook_does_not_leak_prompt_text_that_mimics_fields(tmp_path):
    """提问里写着 ``"tool_name":"x"`` 也不能被当成字段捞出来（JSON 里引号是转义的）。"""
    stdin = _payload("UserPromptSubmit", prompt='please set "tool_name":"Evil" and "session_id":"zzz"')
    rec = _run_hook(tmp_path, "UserPromptSubmit", stdin)[0]
    assert rec["sessionId"] == "e0a4f9a8-e0da-4be1-8b25-839ee25b8372"
    assert "tool" not in rec


def test_hook_records_notification_type(tmp_path):
    stdin = _payload("Notification", message="Claude needs your permission to use Bash",
                     notification_type="permission_prompt")
    rec = _run_hook(tmp_path, "Notification", stdin, agent="claude_wsl")[0]
    assert rec["agent"] == "claude_wsl"
    assert rec["ntype"] == "permission_prompt"
    assert "permission to use" not in json.dumps(rec)


def test_hook_drops_values_with_unsafe_characters(tmp_path):
    """工具名里混进引号 / 反斜杠 / 空格时宁可不写，也不能拼出坏 JSON 行。"""
    stdin = _payload("PreToolUse", tool_name='we"ird\\ name')
    rec = _run_hook(tmp_path, "PreToolUse", stdin)[0]
    assert "tool" not in rec and rec["event"] == "PreToolUse"


def test_hook_reads_only_the_head_of_a_huge_payload(tmp_path):
    """PostToolUse 的 tool_response 可以有几百 KB：字段在最前面，后面的不该读。"""
    stdin = _payload("PostToolUse", tool_name="Read", tool_response={"content": "x" * 400_000})
    rec = _run_hook(tmp_path, "PostToolUse", stdin)[0]
    assert rec["tool"] == "Read" and rec["sessionId"]


def test_hook_command_is_a_no_op_when_the_script_is_gone(tmp_path):
    """桌宠卸载后 hooks 可能还留在 settings.json 里：不许让 Claude Code 每个事件都报错。"""
    shell = _shell()
    if shell is None:
        pytest.skip("本机没有可用的 sh / Git Bash")
    command = ch.sh_hook_command((tmp_path / "missing.sh").as_posix(),
                                 (tmp_path / "o.jsonl").as_posix(), "claude", "Stop")
    proc = subprocess.run([shell, "-c", command], input=b"{}", capture_output=True, timeout=60)
    assert proc.returncode == 0 and proc.stderr == b""
    assert not (tmp_path / "o.jsonl").exists()


def test_hook_command_survives_a_missing_output_directory(tmp_path):
    shell = _shell()
    if shell is None:
        pytest.skip("本机没有可用的 sh / Git Bash")
    script = tmp_path / ch.HOOK_SCRIPT_NAME
    ch.write_hook_script(script)
    command = ch.sh_hook_command(script.as_posix(), (tmp_path / "gone" / "o.jsonl").as_posix(),
                                 "claude", "Stop")
    proc = subprocess.run([shell, "-c", command], input=_payload("Stop").encode(),
                          capture_output=True, timeout=60)
    assert proc.returncode == 0


def test_hook_command_quotes_awkward_paths(tmp_path):
    """用户名带空格 / 单引号 / ``$`` 的路径必须原样到达脚本。"""
    odd = tmp_path / "it's a $HOME dir"
    odd.mkdir()
    records = _run_hook(odd, "Stop", _payload("Stop"))
    assert records and records[0]["event"] == "Stop"


# ---------------------------------------------------------------- 会话标签字段（SessionMeta）

def _transcript(tmp_path: Path, *titles: str, filler: int = 0) -> Path:
    """仿 Claude Code transcript：正文行之间夹着反复追加的 ``ai-title`` 条目。"""
    path = tmp_path / "transcript dir" / "session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "user", "message": {"content": "secret prompt body"}})]
    for title in titles:
        lines.append(json.dumps({"type": "ai-title", "aiTitle": title, "sessionId": "s"},
                                ensure_ascii=False, separators=(",", ":")))
        lines.append(json.dumps({"type": "assistant", "message": {"content": "x" * filler}}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _meta_payload(event: str, transcript: Path | None, cwd: str) -> str:
    return json.dumps({
        "session_id": "e0a4f9a8-e0da-4be1-8b25-839ee25b8372",
        "transcript_path": str(transcript) if transcript else "",
        "cwd": cwd,
        "hook_event_name": event,
        "prompt": "do the secret thing",
    }, separators=(",", ":")) + "\n"


def test_turn_boundaries_record_project_and_latest_session_title(tmp_path):
    """会话小鱼的标签要用：项目文件夹名 + transcript 里**最后**一个 ai-title。"""
    transcript = _transcript(tmp_path, "旧标题", "Fix login redirect loop")
    cwd = str(tmp_path / "my project")

    records = _run_hook(tmp_path, "Stop", _meta_payload("Stop", transcript, cwd))

    assert [r["event"] for r in records] == ["Stop", "SessionMeta"], "元数据单独成行，排在事件之后"
    meta = records[1]
    assert meta["sessionId"] == "e0a4f9a8-e0da-4be1-8b25-839ee25b8372"
    assert meta["project"] == "my project"
    assert meta["title"] == "Fix login redirect loop"
    raw = (tmp_path / "claude.jsonl").read_text(encoding="utf-8")
    assert "secret" not in raw, "对话正文不许落盘"


def test_session_title_survives_non_ascii_and_a_large_transcript(tmp_path):
    transcript = _transcript(tmp_path, "修复登录跳转", filler=50_000)
    meta = _run_hook(tmp_path, "UserPromptSubmit",
                     _meta_payload("UserPromptSubmit", transcript, "/home/u/proj"))[1]
    assert meta["title"] == "修复登录跳转" and meta["project"] == "proj"


def test_meta_falls_back_to_project_only_without_a_title(tmp_path):
    """首次提问时 transcript 里还没有标题（甚至文件都还没有）：只给项目名。"""
    for transcript in (None, tmp_path / "missing.jsonl", _transcript(tmp_path)):
        out = tmp_path / "claude.jsonl"
        if out.exists():
            out.unlink()
        records = _run_hook(tmp_path, "UserPromptSubmit",
                            _meta_payload("UserPromptSubmit", transcript, "/home/u/proj"))
        assert records[0]["event"] == "UserPromptSubmit"
        assert records[1]["project"] == "proj" and records[1]["title"] == ""


def test_title_with_escapes_never_breaks_the_event_line(tmp_path):
    """标题里有引号 / 反斜杠：宁可截短，也不能拼出坏行——更不能连累 Stop 本身。"""
    transcript = _transcript(tmp_path, 'Rename "foo" to bar\\baz')
    records = _run_hook(tmp_path, "Stop", _meta_payload("Stop", transcript, "/home/u/proj"))
    assert records[0]["event"] == "Stop"
    assert records[1]["title"] == "Rename "


def test_tool_events_do_not_touch_the_transcript(tmp_path):
    """高频事件保持零额外开销：不读 transcript，不写 SessionMeta。"""
    transcript = _transcript(tmp_path, "Some title")
    stdin = json.dumps({"session_id": "s1", "transcript_path": str(transcript), "cwd": "/p",
                        "hook_event_name": "PreToolUse", "tool_name": "Bash"},
                       separators=(",", ":")) + "\n"
    for event in ("PreToolUse", "PostToolUse", "SessionStart", "Notification"):
        out = tmp_path / "claude.jsonl"
        if out.exists():
            out.unlink()
        assert [r["event"] for r in _run_hook(tmp_path, event, stdin)] == [event]


# ---------------------------------------------------------------- settings.json 合并

def _entries(marker: str = "new") -> dict:
    return {name: ch.hook_entry(f"{marker}-{name}", shell="bash") for name in ch.HOOK_EVENTS}


def test_hook_entry_shape():
    entry = ch.hook_entry("cmd", shell="bash")
    assert entry == {"matcher": "", "hooks": [{"type": "command", "command": "cmd", "shell": "bash"}],
                     ch.HOOK_FLAG: True}
    assert "shell" not in ch.hook_entry("cmd")["hooks"][0]


def test_merge_is_idempotent_and_keeps_user_hooks():
    user = {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-own-hook"}]}
    data = {"hooks": {"PreToolUse": [user], "Stop": "garbage"}, "other": 1}

    ch.merge_hooks(data, _entries())
    ch.merge_hooks(data, _entries())

    pre = data["hooks"]["PreToolUse"]
    assert pre[0] == user
    assert [g for g in pre if g.get(ch.HOOK_FLAG)] == [ch.hook_entry("new-PreToolUse", shell="bash")]
    assert len(data["hooks"]["Stop"]) == 1, "非列表的脏值按空处理"
    assert data["other"] == 1


def test_merge_removes_our_entries_from_events_we_no_longer_use():
    """旧版本注入过、新版本不再用的事件：升级后不留指向旧脚本的孤儿条目。"""
    stale = {"matcher": "", "hooks": [{"type": "command", "command": "old"}], ch.HOOK_FLAG: True}
    legacy = {"matcher": "", "hooks": [{"type": "command",
                                        "command": 'powershell -File "x\\claude_event_hook.ps1" Stop'}]}
    data = {"hooks": {"SubagentStop": [stale], "Stop": [legacy]}}

    ch.merge_hooks(data, _entries())

    assert "SubagentStop" not in data["hooks"]
    assert data["hooks"]["Stop"] == [ch.hook_entry("new-Stop", shell="bash")]


def test_strip_removes_only_ours_and_drops_emptied_events():
    user = {"matcher": "", "hooks": [{"type": "command", "command": "user_claude_event_hook_cmd"}]}
    data = {"hooks": {"Stop": [user]}}
    ch.merge_hooks(data, _entries())

    ch.strip_hooks(data)

    assert data["hooks"] == {"Stop": [user]}


# ---------------------------------------------------------------- WSL 通道

class _FakeWsl:
    """wsl.exe 替身：记录调用，按脚本内容模拟发行版里的 settings.json。"""

    def __init__(self, content: str | None = None, *, fail: bool = False) -> None:
        self.content = content
        self.fail = fail
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args, *, input_text=None, timeout=30.0):
        self.calls.append((list(args), input_text))
        if self.fail:
            return 1, ""
        if args[:2] == ["-e", "wslpath"]:
            path = args[-1].replace("\\", "/")
            return 0, "/mnt/" + path[0].lower() + path[2:] + "\n"
        if input_text is not None:
            self.content = input_text
            return 0, ""
        return 0, ch._MISSING if self.content is None else self.content


def test_wsl_store_reports_missing_file_as_empty_and_failure_as_none():
    assert ch.WslSettingsStore(_FakeWsl(None)).read() == ""
    assert ch.WslSettingsStore(_FakeWsl('{"a": 1}')).read() == '{"a": 1}'
    assert ch.WslSettingsStore(_FakeWsl(fail=True)).read() is None, "读失败必须能与「文件不存在」区分"


def test_wsl_store_write_pipes_text_and_keeps_file_mode():
    fake = _FakeWsl('{"a": 1}')
    assert ch.WslSettingsStore(fake).write('{"b": 2}') is True
    args, text = fake.calls[-1]
    assert text == '{"b": 2}'
    script = args[-1]
    assert "mv -f" in script and "stat -c %a" in script, "原子替换且照抄原权限"
    assert ch.WslSettingsStore(_FakeWsl(fail=True)).write("{}") is False


def test_to_wsl_path_uses_wslpath_and_rejects_failures():
    assert ch.to_wsl_path(r"C:\Users\me\x", runner=_FakeWsl()) == "/mnt/c/Users/me/x"
    assert ch.to_wsl_path(r"C:\Users\me\x", runner=_FakeWsl(fail=True)) is None


def test_run_wsl_hides_the_console_window(monkeypatch):
    """桌宠由 pythonw / GUI exe 启动：不带 CREATE_NO_WINDOW 每次调用都闪一个终端窗口。"""
    seen: dict = {}

    def _fake_run(argv, **kwargs):
        seen.update(kwargs, argv=argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(ch, "wsl_exe", lambda: "wsl.exe")
    monkeypatch.setattr(ch.subprocess, "run", _fake_run)

    assert ch.run_wsl(["-e", "true"]) == (0, "ok")
    assert seen["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert seen["env"]["WSL_UTF8"] == "1"
    assert seen["timeout"] > 0


def test_run_wsl_folds_failures_into_a_return_code(monkeypatch):
    monkeypatch.setattr(ch, "wsl_exe", lambda: None)
    assert ch.run_wsl(["-e", "true"])[0] != 0

    def _boom(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(ch, "wsl_exe", lambda: "wsl.exe")
    monkeypatch.setattr(ch.subprocess, "run", _boom)
    assert ch.run_wsl(["-e", "true"])[0] != 0


# ---------------------------------------------------------------- 会话收敛

def _ev(event: str, sid: str = "A", **extra) -> dict:
    return {"event": event, "sessionId": sid, **extra}


def _feed(tracker: ClaudeSessionTracker, *records: dict) -> list:
    out: list = []
    for record in records:
        out.extend(tracker.feed(record))
    return out


def test_single_session_turn():
    tracker = ClaudeSessionTracker()
    out = _feed(tracker, _ev("SessionStart"), _ev("UserPromptSubmit"), _ev("PreToolUse"),
                _ev("PostToolUse"), _ev("Stop"))
    assert out == [("state", "thinking"), ("state", "working"), ("state", "working"),
                   ("state", "attention")]
    assert tracker.any_busy() is False


def test_one_session_stopping_does_not_end_the_other():
    """两个会话同时在跑：A 收工只弹提示，Agent 级状态仍是忙；B 收工才真正结束。"""
    tracker = ClaudeSessionTracker()
    _feed(tracker, _ev("UserPromptSubmit", "A"), _ev("UserPromptSubmit", "B"), _ev("PreToolUse", "B"))

    assert tracker.feed(_ev("Stop", "A")) == [("session_done", {"sessionId": "A", "state": "attention"})]
    assert tracker.any_busy() is True
    assert tracker.feed(_ev("PostToolUse", "B")) == [("state", "working")]
    assert tracker.feed(_ev("Stop", "B")) == [("state", "attention")]


def test_idle_session_events_do_not_disturb_a_busy_one():
    tracker = ClaudeSessionTracker()
    _feed(tracker, _ev("UserPromptSubmit", "B"))
    assert _feed(tracker, _ev("SessionStart", "A"), _ev("Stop", "A"), _ev("SessionEnd", "A")) == []
    assert tracker.any_busy() is True


def test_closing_a_busy_session_is_not_reported_as_done():
    tracker = ClaudeSessionTracker()
    _feed(tracker, _ev("UserPromptSubmit", "A"), _ev("UserPromptSubmit", "B"))
    assert tracker.feed(_ev("SessionEnd", "A")) == []
    assert tracker.feed(_ev("SessionEnd", "B")) == [("state", "idle")]


def test_tool_failure_keeps_the_turn_working():
    """工具失败是常态（grep 无匹配、测试没过），回合照常继续；回合失败才是 error。"""
    tracker = ClaudeSessionTracker()
    _feed(tracker, _ev("UserPromptSubmit"))
    assert tracker.feed(_ev("PostToolUseFailure")) == [("state", "working")]
    assert tracker.feed(_ev("StopFailure")) == [("state", "error")]


def test_session_start_mid_turn_is_not_idle():
    """自动压缩上下文会在回合中途触发 SessionStart(source=compact)。"""
    tracker = ClaudeSessionTracker()
    _feed(tracker, _ev("UserPromptSubmit"), _ev("PreToolUse"))
    assert tracker.feed(_ev("SessionStart")) == []
    assert tracker.any_busy() is True


def test_permission_prompt_is_requested_once_and_resolved_by_the_next_event():
    tracker = ClaudeSessionTracker()
    _feed(tracker, _ev("UserPromptSubmit"), _ev("PreToolUse"))
    approval = {"approvalId": "claude-permission:A"}

    assert tracker.feed(_ev("Notification", ntype="permission_prompt")) == [("approval_request", approval)]
    assert tracker.feed(_ev("Notification", ntype="permission_prompt")) == [], "同一次等待不重复提示"
    assert tracker.any_busy() is True, "等批准不算收工"
    assert tracker.feed(_ev("PostToolUse")) == [("approval_resolved", approval), ("state", "working")]


def test_permission_prompts_of_two_sessions_resolve_independently():
    tracker = ClaudeSessionTracker()
    _feed(tracker, _ev("PreToolUse", "A"), _ev("PreToolUse", "B"),
          _ev("Notification", "A", ntype="permission_prompt"),
          _ev("Notification", "B", ntype="elicitation_dialog"))
    out = tracker.feed(_ev("PostToolUse", "B"))
    assert ("approval_resolved", {"approvalId": "claude-permission:B"}) in out
    assert ("approval_resolved", {"approvalId": "claude-permission:A"}) not in out


def test_other_notifications_are_ignored():
    tracker = ClaudeSessionTracker()
    assert tracker.feed(_ev("Notification", ntype="auth_success")) == []
    assert tracker.feed(_ev("Notification", ntype="idle_prompt")) == [], "本来就闲着：无事发生"


def test_idle_prompt_releases_an_interrupted_session():
    """Esc 打断不发 Stop：会话会一直占着「忙」。等输入满 60 秒的通知说明它早停了。"""
    tracker = ClaudeSessionTracker()
    _feed(tracker, _ev("UserPromptSubmit"), _ev("PreToolUse"))
    assert tracker.feed(_ev("Notification", ntype="idle_prompt")) == [("state", "attention")]
    assert tracker.any_busy() is False


def test_records_without_session_id_behave_as_one_session():
    """旧脚本写的行没有 sessionId：按单会话处理，行为与改造前一致。"""
    tracker = ClaudeSessionTracker()
    out = _feed(tracker, {"event": "UserPromptSubmit"}, {"event": "PreToolUse", "tool": "Bash"},
                {"event": "Stop"})
    assert out == [("state", "thinking"), ("state", "working"), ("state", "attention")]


def test_explicit_state_wins_and_unknown_events_are_ignored():
    tracker = ClaudeSessionTracker()
    assert tracker.feed({"state": "working", "sessionId": "A"}) == [("state", "working")]
    assert tracker.feed(_ev("SomethingNew")) == []
    assert tracker.feed({"state": "idle", "sessionId": "A"}) == [("state", "idle")]


def test_session_table_is_bounded():
    tracker = ClaudeSessionTracker()
    for i in range(ClaudeSessionTracker._MAX_SESSIONS + 20):
        tracker.feed(_ev("UserPromptSubmit", f"s{i}"))
    assert len(tracker._busy) == ClaudeSessionTracker._MAX_SESSIONS
    assert "s0" not in tracker._busy, "先淘汰最久没动静的会话"


def test_reset_forgets_everything():
    tracker = ClaudeSessionTracker()
    _feed(tracker, _ev("PreToolUse"), _ev("Notification", ntype="permission_prompt"))
    tracker.reset()
    assert tracker.any_busy() is False
    assert tracker.feed(_ev("Stop")) == []


# ---------------------------------------------------------------- 逐会话更新（会话小鱼的数据源）

def _updates(tracker: ClaudeSessionTracker, *records: dict) -> list[dict]:
    for record in records:
        tracker.feed(record)
    return tracker.take_session_updates()


def _meta(sid: str = "A", **fields) -> dict:
    return {"event": "SessionMeta", "sessionId": sid, **fields}


def test_session_appears_on_first_prompt_and_follows_the_turn():
    tracker = ClaudeSessionTracker()
    assert _updates(tracker, _ev("SessionStart")) == [], "只开着没提问的会话不出场"

    assert _updates(tracker, _ev("UserPromptSubmit"), _meta(project="dsh-pet", title="")) == [
        {"sessionId": "A", "phase": "working", "title": "", "project": ""},
        {"sessionId": "A", "phase": "working", "title": "", "project": "dsh-pet"},
    ]
    assert _updates(tracker, _ev("PreToolUse"), _ev("PostToolUse")) == [], "状态没变不重复上报"
    assert _updates(tracker, _ev("Stop"), _meta(project="dsh-pet", title="Fix login loop")) == [
        {"sessionId": "A", "phase": "resting", "title": "", "project": "dsh-pet"},
        {"sessionId": "A", "phase": "resting", "title": "Fix login loop", "project": "dsh-pet"},
    ]
    assert _updates(tracker, _ev("UserPromptSubmit"), _meta(project="dsh-pet", title="")) == [
        {"sessionId": "A", "phase": "working", "title": "Fix login loop", "project": "dsh-pet"},
    ], "这次没读到标题（transcript 窗口里没有）：保留已知的，不清空"
    assert _updates(tracker, _ev("SessionEnd")) == [
        {"sessionId": "A", "phase": "gone", "title": "Fix login loop", "project": "dsh-pet"},
    ]
    assert _updates(tracker, _ev("Stop"), _meta(title="late")) == [], "离场后的迟到记录不复活它"


def test_sessions_report_independently():
    tracker = ClaudeSessionTracker()
    updates = _updates(tracker, _ev("UserPromptSubmit", "A"), _ev("UserPromptSubmit", "B"), _ev("Stop", "A"))
    assert [(u["sessionId"], u["phase"]) for u in updates] == [
        ("A", "working"), ("B", "working"), ("A", "resting")]


def test_waiting_for_approval_is_its_own_phase():
    tracker = ClaudeSessionTracker()
    updates = _updates(tracker, _ev("PreToolUse"), _ev("Notification", ntype="permission_prompt"),
                       _ev("PostToolUse"))
    assert [u["phase"] for u in updates] == ["working", "waiting", "working"]

    updates = _updates(tracker, _ev("Notification", ntype="permission_prompt"), _ev("Stop"))
    assert [u["phase"] for u in updates] == ["waiting", "resting"], "被拒绝后直接收工"


def test_session_first_seen_mid_turn_still_appears():
    """桌宠在回合中途才启动：没见到提问，第一眼就是工具事件或权限确认。"""
    tracker = ClaudeSessionTracker()
    assert [u["phase"] for u in _updates(tracker, _ev("PostToolUse", "A"))] == ["working"]
    assert [u["phase"] for u in _updates(tracker, _ev("Notification", "B", ntype="permission_prompt"))] == ["waiting"]


def test_interrupted_session_rests_after_the_idle_notice():
    tracker = ClaudeSessionTracker()
    updates = _updates(tracker, _ev("UserPromptSubmit"), _ev("Notification", ntype="idle_prompt"))
    assert [u["phase"] for u in updates] == ["working", "resting"]


def test_session_labels_are_cleaned_and_capped():
    tracker = ClaudeSessionTracker()
    update = _updates(tracker, _ev("UserPromptSubmit"),
                      _meta(project="  my   project ", title="T" * 100))[-1]
    assert update["project"] == "my project"
    assert len(update["title"]) == ClaudeSessionTracker._LABEL_MAX


def test_session_updates_are_drained_and_reset_forgets_sessions():
    tracker = ClaudeSessionTracker()
    tracker.feed(_ev("UserPromptSubmit"))
    assert len(tracker.take_session_updates()) == 1
    assert tracker.take_session_updates() == []
    tracker.reset()
    assert _updates(tracker, _ev("Stop")) == []


def test_evicted_session_leaves_the_stage():
    tracker = ClaudeSessionTracker()
    for i in range(ClaudeSessionTracker._MAX_SESSIONS + 1):
        tracker.feed(_ev("UserPromptSubmit", f"s{i}"))
    updates = tracker.take_session_updates()
    assert {"sessionId": "s0", "phase": "gone", "title": "", "project": ""} in updates


def test_git_bash_lookup_is_windows_only(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert ch.find_git_bash() is None
    assert ch.wsl_exe() is None


def test_git_bash_lookup_honours_the_claude_code_override(tmp_path, monkeypatch):
    bash = tmp_path / "bash.exe"
    bash.write_bytes(b"")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(bash))
    assert ch.find_git_bash() == str(bash)
    assert os.path.isfile(ch.find_git_bash())


# ---------------------------------------------------------------- 会话汇总（灵动岛卡片）

def _s(agent: str, phase: str, **fields) -> dict:
    return {"agent": agent, "sessionId": fields.pop("sid", "0123456789abcdef"), "phase": phase,
            "title": "", "project": "", **fields}


def test_summary_without_sessions_says_so():
    headline, detail = ch.summarize_sessions([])
    assert headline == "Claude Code · 没有在用的会话"
    assert detail


def test_summary_counts_by_phase_and_puts_what_needs_you_first():
    headline, detail = ch.summarize_sessions([
        _s("claude", "resting", title="Old chat"),
        _s("claude", "working", project="dsh-pet"),
        _s("claude_wsl", "waiting", project="work"),
        _s("claude", "working", sid="abcdef0123"),
    ])
    assert headline == "Claude Code · 1 个等你批准 · 2 个在干活 · 1 个休息中"
    assert detail == "work (WSL) · 等你批准 ｜ dsh-pet · 工作中 等 4 个"


def test_summary_lists_every_session_when_they_fit():
    _headline, detail = ch.summarize_sessions([_s("claude", "working", title="Fix login loop")])
    assert detail == "Fix login loop · 工作中"


def test_capsule_counts_follow_working_resting_waiting_and_skip_empty_phases():
    """灵动岛胶囊上的计数：「2 工作中 1 休息中 2 等待中」，没有的阶段不占地方。"""
    sessions = [
        _s("claude", "waiting"), _s("claude", "working"), _s("claude_wsl", "resting"),
        _s("claude", "working"), _s("claude_wsl", "waiting"), _s("claude", "gone"),
    ]
    assert ch.session_counts(sessions) == [
        ("working", "2 工作中"), ("resting", "1 休息中"), ("waiting", "2 等待中")]
    assert ch.session_counts([_s("claude", "resting")]) == [("resting", "1 休息中")]
    assert ch.session_counts([]) == []


def test_session_label_prefers_title_then_project_then_short_id():
    assert ch.session_label("claude", {"title": "T", "project": "P", "sessionId": "abc"}) == "T"
    assert ch.session_label("claude", {"title": "", "project": "P", "sessionId": "abc"}) == "P"
    assert ch.session_label("claude_wsl", {"sessionId": "0123456789"}) == "01234567 (WSL)"
    assert ch.session_label("claude", {}) == "Claude Code"
