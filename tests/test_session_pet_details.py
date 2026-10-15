# -*- coding: utf-8 -*-
"""会话小鱼的详情、跳转与专属右键菜单。

三层：纯逻辑（``claude_session_info`` 解析会话记录 / 运行清单，``claude_session_jump``
挑窗口）、数据通路（hook 脚本 → 收敛器 → 监视器），以及界面（详情卡、菜单、单击）。

样本数据按 2026-10 实机见到的格式造（Claude Code 2.1.283 / 2.1.296）。这两个文件都
是 Claude Code 的内部格式，所以每条解析用例都带一个「格式不认识 → 留空」的断言。

纪律：offscreen；不读真实的 ~/.claude，不切真实窗口（后端全部注入）；后台线程的
结果用轮询事件循环等到，不 sleep。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import claude_hooks as ch
from pet import claude_session_info as si
from pet import claude_session_jump as sj
from pet.claude_hooks import ClaudeSessionTracker
from pet.claude_session_jump import JumpResult, Window
from pet.overlay_session_pets import SessionPetController
from tests.test_claude_hooks import _run_hook
from tests.test_overlay_spawn import _make_persistent_shell

app = QApplication.instance() or QApplication([])

SID = "e0a4f9a8-e0da-4be1-8b25-839ee25b8372"


def _line(**entry) -> str:
    return json.dumps(entry, ensure_ascii=False, separators=(",", ":"))


def _transcript_text(*prompts: str, branch: str = "main", entry: str = "claude-vscode") -> str:
    lines = []
    for index, prompt in enumerate(prompts):
        lines.append(_line(type="user", message={"content": "正文不该被当成最近的问题"},
                           cwd="C:\\proj", gitBranch=branch, entrypoint=entry,
                           version="2.1.283", sessionId=SID))
        lines.append(_line(type="last-prompt", lastPrompt=prompt, leafUuid="x", sessionId=SID))
        lines.append(_line(type="ai-title", aiTitle=f"标题 {index}", sessionId=SID))
    return "\n".join(lines) + "\n"


# ================================================================ 会话记录 / 运行清单
def test_transcript_tail_gives_the_latest_prompt_branch_and_entrypoint():
    parsed = si.parse_transcript_tail(_transcript_text("第一个问题", "第二个\n问题", branch="feature/x"))
    assert parsed["last_prompt"] == "第二个 问题", "取最后一次提问；换行压成空格"
    assert parsed["title"] == "标题 1"
    assert (parsed["git_branch"], parsed["entrypoint"], parsed["cwd"]) == (
        "feature/x", "claude-vscode", "C:\\proj")


def test_transcript_tail_survives_a_cut_first_line_and_unknown_formats():
    text = _transcript_text("问题")
    assert si.parse_transcript_tail(text[25:])["last_prompt"] == "问题", "尾部窗口切在一行中间"
    assert si.parse_transcript_tail("not json\n{\"type\":\"future-thing\"}\n[1,2]\n") == {}
    assert si.parse_transcript_tail("") == {}


def test_long_prompts_are_cut_for_display():
    parsed = si.parse_transcript_tail(_transcript_text("长" * 2000))
    assert len(parsed["last_prompt"]) == si.PROMPT_MAX and parsed["last_prompt"].endswith("…")


def _registry_entry(pid=100, sid=SID, **over) -> dict:
    return {"pid": pid, "sessionId": sid, "cwd": "C:\\proj", "startedAt": 1791671005108,
            "procStart": "134361446043693149", "version": "2.1.283", "kind": "interactive",
            "entrypoint": "claude-vscode", "name": "proj-53", "status": "busy",
            "updatedAt": 1791704124060, **over}


def test_registry_keeps_the_most_recent_entry_per_session_and_skips_junk():
    old = _registry_entry(pid=1, updatedAt=10)
    new = _registry_entry(pid=2, updatedAt=20)
    registry = si.parse_registry([json.dumps(old), "garbage", json.dumps(new),
                                  json.dumps({"sessionId": "no-pid"}), "[]"])
    assert list(registry) == [SID] and registry[SID]["pid"] == 2


def test_load_local_merges_registry_and_transcript(tmp_path):
    sessions = tmp_path / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "100.json").write_text(json.dumps(_registry_entry()), encoding="utf-8")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(_transcript_text("怎么修这个 bug", branch="fix/login"), encoding="utf-8")
    detail = si.from_session("claude", {"sessionId": SID, "title": "修登录", "project": "proj",
                                        "transcript": str(transcript), "phase": "working"})

    si.load_local(detail, home=tmp_path, alive=lambda entry: True)

    assert (detail.pid, detail.entrypoint, detail.name) == (100, "claude-vscode", "proj-53")
    assert detail.last_prompt == "怎么修这个 bug" and detail.git_branch == "fix/login"
    assert detail.alive is True and detail.cwd == "C:\\proj"
    assert detail.started_at == pytest.approx(1791671005.108)
    assert detail.entry_text == "VS Code 插件"
    assert detail.resume_command == f"claude --resume {SID}"


def test_missing_files_leave_the_detail_usable(tmp_path):
    detail = si.from_session("claude", {"sessionId": SID, "title": "T",
                                        "transcript": str(tmp_path / "nope.jsonl")})
    si.load_local(detail, home=tmp_path)
    assert detail.title == "T" and detail.last_prompt == "" and detail.alive is None
    assert si.local_liveness([SID], home=tmp_path) == {SID: None}, "清单里没有 ≠ 会话没了"


def test_liveness_reports_dead_only_for_sessions_the_registry_knows(tmp_path):
    sessions = tmp_path / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "100.json").write_text(json.dumps(_registry_entry()), encoding="utf-8")
    verdicts = si.local_liveness([SID, "other"], home=tmp_path, alive=lambda entry: False)
    assert verdicts == {SID: False, "other": None}


def test_process_alive_rejects_a_reused_pid(monkeypatch):
    """进程号对得上但启动时间对不上 = 号被别的进程复用了，原来那个会话已经没了。"""
    import psutil

    me = psutil.Process()
    filetime = int((me.create_time() + si._FILETIME_EPOCH_S) * 1e7)
    monkeypatch.setattr(si.sys, "platform", "win32")
    assert si.process_alive({"pid": me.pid, "procStart": str(filetime)}) is True
    assert si.process_alive({"pid": me.pid, "procStart": str(filetime - int(3600 * 1e7))}) is False
    assert si.process_alive({"pid": me.pid, "procStart": "不是数字"}) is True, "格式变了：只看进程在不在"
    assert si.process_alive({"pid": "x"}) is None


# ---------------------------------------------------------------- WSL
def _wsl_output(tail: str = "") -> str:
    live = _registry_entry(pid=501, sid="live", procStart="777", entrypoint="cli",
                           cwd="/home/u/proj")
    dead = _registry_entry(pid=502, sid="dead", procStart="888")
    reused = _registry_entry(pid=503, sid="reused", procStart="999")
    return "\n".join([
        "@@distro Ubuntu-24.04",
        "@@reg 777 " + json.dumps(live),
        "@@env TERM_PROGRAM=vscode",
        "@@reg  " + json.dumps(dead),                 # 进程不在：启动时刻一栏是空的
        "@@reg 123 " + json.dumps(reused),            # 进程号被复用
        "@@tail", tail])


def test_wsl_output_is_split_into_registry_liveness_env_and_tail():
    parsed = si.parse_wsl_output(_wsl_output(_transcript_text("WSL 里的问题")))
    assert parsed["distro"] == "Ubuntu-24.04"
    assert parsed["alive"] == {"live": True, "dead": False, "reused": False}
    assert parsed["env"] == {"TERM_PROGRAM": "vscode"}
    assert si.parse_transcript_tail(parsed["tail"])["last_prompt"] == "WSL 里的问题"


def test_load_wsl_uses_one_call_and_never_injects_a_strange_session_id():
    calls = []

    def runner(args):
        calls.append(args)
        return 0, _wsl_output(_transcript_text("问"))

    detail = si.load_wsl(si.from_session("claude_wsl", {
        "sessionId": "live", "transcript": "/home/u/.claude/projects/p/live.jsonl"}), runner=runner)
    assert len(calls) == 1 and calls[0][-2:] == ["/home/u/.claude/projects/p/live.jsonl", "live"]
    assert (detail.distro, detail.alive, detail.entrypoint) == ("Ubuntu-24.04", True, "cli")
    assert detail.extra["env"] == {"TERM_PROGRAM": "vscode"}
    assert detail.entry_text == "终端 · WSL"

    si.load_wsl(si.from_session("claude_wsl", {"sessionId": 'x";rm -rf ~;"'}), runner=runner)
    assert calls[-1][-1] == "", "会话 ID 会进 grep 模式：不是 UUID 字符集就不传"


def test_wsl_failure_is_not_a_verdict():
    assert si.wsl_liveness(["a"], runner=lambda args: (1, "")) == {"a": None}
    detail = si.from_session("claude_wsl", {"sessionId": "a", "title": "T"})
    assert si.load_wsl(detail, runner=lambda args: (127, "")).title == "T"


# ================================================================ 数据通路
def test_hook_passes_the_working_directory_and_transcript_path(tmp_path):
    transcript = tmp_path / "t dir" / "session.jsonl"
    transcript.parent.mkdir()
    transcript.write_text(_transcript_text("绝密问题"), encoding="utf-8")
    cwd = "C:\\Users\\me\\我的 项目"
    stdin = json.dumps({"session_id": SID, "transcript_path": str(transcript), "cwd": cwd,
                        "hook_event_name": "UserPromptSubmit", "prompt": "绝密问题"},
                       ensure_ascii=False, separators=(",", ":")) + "\n"

    meta = _run_hook(tmp_path, "UserPromptSubmit", stdin)[1]

    assert meta["cwd"] == cwd, "Windows 路径的反斜杠原样回来"
    assert Path(meta["transcript"]) == transcript
    raw = (tmp_path / "claude.jsonl").read_text(encoding="utf-8")
    assert "绝密问题" not in raw, "提问正文不落盘：详情里的问题是点开时现读的"


def _feed(tracker: ClaudeSessionTracker, *records) -> list[dict]:
    for record in records:
        tracker.feed(record)
    return tracker.take_session_updates()


def test_tracker_carries_paths_and_the_last_tool_with_session_updates():
    tracker = ClaudeSessionTracker()
    meta = {"event": "SessionMeta", "sessionId": "A", "project": "p", "title": "",
            "cwd": "/home/u/p", "transcript": "/home/u/.claude/projects/p/A.jsonl"}
    updates = _feed(tracker, {"event": "UserPromptSubmit", "sessionId": "A"}, meta)
    assert updates[-1] == {"sessionId": "A", "phase": "working", "title": "", "project": "p",
                           "cwd": "/home/u/p", "transcript": "/home/u/.claude/projects/p/A.jsonl"}

    assert _feed(tracker, meta) == [], "同样的元数据不重复上报"
    assert _feed(tracker, {"event": "PreToolUse", "sessionId": "A", "tool": "Bash"}) == [], \
        "工具每次调用都变：不单独上报"
    waiting = _feed(tracker, {"event": "Notification", "sessionId": "A", "ntype": "permission_prompt"})
    assert waiting[-1]["phase"] == "waiting" and waiting[-1]["tool"] == "Bash"
    assert tracker.session_ids() == ["A"]

    moved = _feed(tracker, {**meta, "cwd": "/home/u/other"})
    assert len(moved) == 1 and moved[0]["cwd"] == "/home/u/other", "只有路径变了也要让呈现层知道"


def test_monitor_retires_sessions_whose_process_is_gone(tmp_path, monkeypatch):
    """被直接杀掉的 Claude Code 不发 SessionEnd：靠核对进程把它的会话收掉。"""
    from pet.agent_link import ClaudeCodeMonitor
    from tests.test_claude_link import _append, _monitor

    monkeypatch.setattr(ClaudeCodeMonitor, "_LIVENESS_PERIOD_S", 0.0)
    asked = []

    def liveness(ids):
        asked.append(sorted(ids))
        return {"dead": False, "alive": True, "unknown": None}

    monkeypatch.setattr(si, "local_liveness", liveness)
    mon, got = _monitor(tmp_path)
    try:
        _append(mon, *(json.dumps({"ts": 1, "agent": "claude", "event": "UserPromptSubmit",
                                   "sessionId": sid}) + "\n" for sid in ("dead", "alive", "unknown")))
        mon._poll()
        assert asked and asked[-1] == ["alive", "dead", "unknown"]
        gone = [s[1] for s in got.sessions if s[2] == "gone"]
        assert gone == ["dead"], "清单里没有记录（None）的会话不动"
        assert mon._sessions.session_ids() == ["alive", "unknown"]
    finally:
        mon.stop()


# ================================================================ 挑窗口 / 跳转
CODE = "code.exe"
WINDOWS = [
    Window(1, 10, "oncall-claude [WSL: Ubuntu-24.04] - Alert.md", CODE),
    Window(2, 10, "dsh-pet-indesktop - overlay_shell.py", CODE),          # 自定义标题：文件夹在前
    Window(3, 10, "main.py - Flare - Visual Studio Code", CODE),          # 默认标题：文件夹在中间
    Window(4, 20, "Ubuntu-24.04", "windowsterminal.exe"),
    Window(5, 30, "dsh-pet-indesktop - 资源管理器", "explorer.exe"),
]


def test_vscode_window_is_found_by_its_workspace_folder_segment():
    find = sj.find_vscode_window
    assert find(WINDOWS, r"c:\Users\me\Github\dsh-pet-indesktop").hwnd == 2
    assert find(WINDOWS, r"C:\code\Flare").hwnd == 3
    assert find(WINDOWS, r"C:\code\Flare\src\deep").hwnd == 3, "会话在工作区的子目录里"
    assert find(WINDOWS, "/home/u/Github/oncall-claude", wsl=True).hwnd == 1
    assert find(WINDOWS, "/home/u/Github/oncall-claude") is None, "WSL 窗口不冒充本机项目"
    assert find(WINDOWS, r"C:\x\dsh-pet-indesktop", wsl=True) is None
    assert find(WINDOWS, r"C:\nowhere\unknown") is None
    assert find(WINDOWS, "") is None


def test_terminal_session_host_is_the_first_ancestor_that_owns_a_window():
    chain = [(900, "claude.exe"), (800, "pwsh.exe"), (20, "WindowsTerminal.exe"), (4, "svchost.exe")]
    assert sj.find_host_window(chain, WINDOWS, r"C:\Users\me").hwnd == 4
    in_vscode = [(900, "claude.exe"), (800, "pwsh.exe"), (11, "Code.exe"), (10, "Code.exe")]
    assert sj.find_host_window(in_vscode, WINDOWS, r"C:\code\Flare").hwnd == 3
    assert sj.find_host_window(in_vscode, WINDOWS, r"C:\Users\me").hwnd == 2, \
        "认不出工作区：取最靠前的本机窗口，不取 WSL 远程窗口"
    assert sj.find_host_window([(900, "claude.exe"), (1, "x.exe")], WINDOWS, "") is None


def test_wsl_terminal_session_uses_its_environment_to_pick_the_kind_of_window():
    detail = si.SessionDetail(agent="claude_wsl", cwd="/home/u/Github/oncall-claude",
                              distro="Ubuntu-24.04")
    assert sj.find_wsl_terminal_window(WINDOWS, detail, {"TERM_PROGRAM": "vscode"}).hwnd == 1
    assert sj.find_wsl_terminal_window(WINDOWS, detail, {"WT_SESSION": "guid"}).hwnd == 4
    assert sj.find_wsl_terminal_window(WINDOWS, detail, {}).hwnd == 4


class _Desk:
    """假桌面：记录跳转做了哪些事、按什么顺序。"""

    def __init__(self, windows=WINDOWS, focus_ok=True, chain=()):
        self.log: list = []
        self.kwargs = dict(
            windows=lambda: list(windows),
            focus=lambda hwnd: (self.log.append(("focus", hwnd)), focus_ok)[1],
            chain=lambda pid: list(chain),
            uri=lambda uri: (self.log.append(("uri", uri)), True)[1],
            vscode=lambda detail, target="": (self.log.append(("code", target or detail.cwd)), True)[1],
            workspaces=lambda: [],       # 不读真实的 VS Code 窗口记录（那一路见 test_session_jump_workspaces）
            sleep=lambda seconds: None)


def _vscode_detail(**over) -> si.SessionDetail:
    return si.SessionDetail(**{"agent": "claude", "session_id": SID, "entrypoint": "claude-vscode",
                               "cwd": r"c:\Users\me\Github\dsh-pet-indesktop", "alive": True, **over})


def test_vscode_jump_brings_the_right_window_forward_before_opening_the_session():
    desk = _Desk()
    result = sj.jump(_vscode_detail(), **desk.kwargs)
    assert result.ok
    assert desk.log == [("focus", 2), ("uri", f"vscode://anthropic.claude-code/open?session={SID}")]


def test_vscode_jump_never_sends_the_link_to_the_wrong_window():
    """链接在「当前聚焦的窗口」里生效；窗口没调对就发，插件会新开一个空对话。"""
    desk = _Desk(focus_ok=False)
    result = sj.jump(_vscode_detail(), **desk.kwargs)
    assert not result.ok and desk.log == [("focus", 2)]


def test_vscode_jump_falls_back_to_the_code_command_when_no_title_matches():
    desk = _Desk()
    result = sj.jump(_vscode_detail(cwd=r"C:\somewhere\else"), **desk.kwargs)
    assert result.ok and [step[0] for step in desk.log] == ["code", "uri"]


def test_jump_refuses_a_dead_session_and_points_to_the_resume_command():
    desk = _Desk()
    result = sj.jump(_vscode_detail(alive=False), **desk.kwargs)
    assert not result.ok and "恢复命令" in result.message and desk.log == []


def test_terminal_jump_focuses_the_host_window_and_says_the_tab_is_up_to_you():
    chain = [(900, "claude.exe"), (800, "pwsh.exe"), (20, "WindowsTerminal.exe")]
    desk = _Desk(chain=chain)
    detail = si.SessionDetail(agent="claude", session_id=SID, entrypoint="cli", pid=900,
                              cwd=r"C:\Users\me", alive=True)
    result = sj.jump(detail, **desk.kwargs)
    assert result.ok and desk.log == [("focus", 4)] and "标签页" in result.message

    lost = sj.jump(detail, **_Desk(chain=[(900, "claude.exe")]).kwargs)
    assert not lost.ok


def test_explorer_path_maps_wsl_paths_to_the_network_share():
    assert sj.explorer_path(si.SessionDetail(cwd=r"C:\proj")) == r"C:\proj"
    wsl = si.SessionDetail(agent="claude_wsl", cwd="/home/u/proj", distro="Ubuntu-24.04")
    assert sj.explorer_path(wsl) == r"\\wsl.localhost\Ubuntu-24.04\home\u\proj"
    assert sj.explorer_path(si.SessionDetail(agent="claude_wsl", cwd="/home/u/proj")) == ""


# ================================================================ 界面
@pytest.fixture
def shell(tmp_path, monkeypatch):
    monkeypatch.setattr(SessionPetController, "WORK_CLIPS", ("act1",))
    monkeypatch.setattr(SessionPetController, "REST_CLIPS", ("idle1",))
    monkeypatch.setattr(SessionPetController, "REVIEW_CLIPS", ("click1",))
    shell, _made = _make_persistent_shell(tmp_path, {"scale": 0.85})
    try:
        yield shell
    finally:
        shell.session_actions.close()
        shell._delete_runtime_marker()


def _session(shell, sid="A", **over):
    update = {"sessionId": sid, "phase": "working", "title": "修登录", "project": "proj",
              "cwd": r"C:\code\proj", "transcript": r"C:\t\A.jsonl", **over}
    shell.session_pets.on_session_update("claude", update)
    return shell.session_pets.sprite_of(("claude", sid))


def _labels(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _pump(predicate, budget_s: float = 20.0) -> bool:
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
    return False


def test_session_fish_gets_its_own_short_menu_and_the_main_fish_keeps_the_full_one(shell):
    fish = _session(shell)
    menu = shell._build_menu_for(fish)
    assert _labels(menu) == ["修登录", "跳到这个对话", "查看详情", "打开项目文件夹", "复制恢复命令",
                             "复制会话 ID", "让这只离场", "会话小鱼设置"]
    assert not menu.actions()[0].isEnabled(), "第一行只是告诉你这是哪个会话"
    main = _labels(shell._build_menu_for(shell.sprite))
    assert "跳到这个对话" not in main and len(main) > 8


def test_controller_remembers_details_without_disturbing_the_session_list(shell):
    fish = _session(shell)
    ctl = shell.session_pets
    assert ctl.key_of(fish) == ("claude", "A") and ctl.key_of(shell.sprite) is None
    assert ctl.describe(("claude", "A"))["cwd"] == r"C:\code\proj"
    assert ctl.sessions() == [{"agent": "claude", "sessionId": "A", "phase": "working",
                               "title": "修登录", "project": "proj"}], "灵动岛用的清单不带路径"
    started = ctl.since(("claude", "A"))
    _session(shell, tool="Bash")                      # 同一阶段的更新不重置计时
    assert ctl.since(("claude", "A")) == started
    assert ctl.describe(("claude", "A"))["tool"] == "Bash"


def test_clicking_a_session_fish_opens_its_detail_card(shell):
    fish = _session(shell)
    actions = shell.session_actions

    def loader(detail):
        detail.last_prompt, detail.git_branch = "为什么登录会跳两次？", "fix/login"
        detail.entrypoint, detail.alive = "claude-vscode", True
        return detail

    actions.loader = loader
    shell._on_sprite_click(fish, "")

    card = actions._card
    assert card is not None and card.isVisible() and card.key == ("claude", "A")
    assert card.title_label.text() == "修登录"
    assert card.status_label.text().startswith("工作中 · 已")
    assert card.prompt_label.text() == "读取中…"
    assert _pump(lambda: card.prompt_label.text() == "为什么登录会跳两次？")
    assert card.where_label.text() == r"VS Code 插件 · C:\code\proj · 分支 fix/login"


def test_clicking_the_main_fish_does_not_open_a_session_card(shell):
    _session(shell)
    shell._on_sprite_click(shell.sprite, "")
    assert shell.session_actions._card is None


def test_jump_reports_its_outcome_on_the_card(shell):
    fish = _session(shell)
    actions = shell.session_actions
    actions.loader = lambda detail: detail
    seen = []
    actions.jumper = lambda detail, wsl_env=None: (seen.append(detail.session_id),
                                                    JumpResult(True, "已跳到 VS Code 里的这个对话"))[1]
    actions.show_card(fish)
    actions._card.jump_btn.click()
    assert _pump(lambda: actions._card.result_label.text() == "已跳到 VS Code 里的这个对话")
    assert seen == ["A"]


def test_jumping_to_a_finished_session_marks_it_as_seen(shell):
    """回合结束后是「等你回复」；点了「跳到对话」就算看过，落回「休息中」。"""
    fish = _session(shell)
    _session(shell, phase="resting")
    actions = shell.session_actions
    actions.loader = lambda detail: detail
    actions.jumper = lambda detail, wsl_env=None: JumpResult(True, "已跳到 VS Code 里的这个对话")
    actions.show_card(fish)
    card = actions._card
    assert card.status_label.text().startswith("等你回复 · 已")
    assert fish.caption == "修登录 · 等你回复"

    card.jump_btn.click()

    assert fish.caption == "修登录 · 休息中"
    assert card.status_label.text().startswith("休息中 · 已"), "开着的卡片跟着换"
    assert _pump(lambda: card.result_label.text() == "已跳到 VS Code 里的这个对话")


def test_the_menu_jump_also_marks_the_session_as_seen(shell):
    fish = _session(shell)
    _session(shell, phase="resting")
    actions = shell.session_actions
    actions.loader = lambda detail: detail
    done = []
    actions.jumper = lambda detail, wsl_env=None: (done.append(1), JumpResult(True, "ok"))[1]

    assert actions.jump(fish) is True

    assert fish.caption == "修登录 · 休息中"
    assert _pump(lambda: bool(done))


def test_copy_and_open_folder_use_the_sessions_own_data(shell):
    fish = _session(shell)
    actions = shell.session_actions
    opened = []
    actions.opener = lambda path: (opened.append(path), True)[1]

    assert actions.copy_resume(fish) and QApplication.clipboard().text() == "claude --resume A"
    assert actions.copy_session_id(fish) and QApplication.clipboard().text() == "A"
    assert actions.open_folder(fish) and opened == [r"C:\code\proj"]
    assert actions.copy_resume(shell.sprite) is False, "主肥鱼不是会话"


def test_dismissed_fish_stays_away_until_its_session_closes(shell):
    fish = _session(shell)
    ctl = shell.session_pets
    assert shell.session_actions.dismiss(fish) is True
    assert not shell.is_session_pet(fish)

    _session(shell, phase="resting")
    _session(shell, phase="working")
    assert ctl.sprite_of(("claude", "A")) is None, "这个会话还开着：不再为它生小鱼"
    assert [s["sessionId"] for s in ctl.sessions()] == ["A"], "会话本身照常记着"

    ctl.on_session_update("claude", {"sessionId": "A", "phase": "gone"})
    assert _session(shell) is not None, "会话关掉再开（同一个 ID 被恢复）：重新出场"


def test_card_closes_when_its_session_goes_away(shell):
    fish = _session(shell)
    actions = shell.session_actions
    actions.loader = lambda detail: detail
    actions.show_card(fish)
    assert actions._card.isVisible()
    shell.session_pets.on_session_update("claude", {"sessionId": "A", "phase": "gone"})
    assert not actions._card.isVisible()


def test_status_and_elapsed_wording():
    from pet.session_pet_ui import elapsed_text, status_line

    assert [elapsed_text(s) for s in (5, 200, 3600, 3900)] == ["刚刚", "3 分钟", "1 小时", "1 小时 5 分"]
    waiting = si.SessionDetail(phase="waiting", tool="Bash")
    assert status_line(waiting, 1000.0, now=1300.0) == "在等你批准：Bash · 已 5 分钟"
    assert status_line(si.SessionDetail(phase="resting"), None) == ch.PHASE_TEXT["resting"]
    assert status_line(si.SessionDetail(phase="review"), 1000.0, now=1660.0) == "等你回复 · 已 11 分钟"


def test_transcript_is_found_by_session_id_when_the_hook_has_not_sent_its_path_yet(tmp_path):
    """肥鱼刚启动、会话正在回合中途：路径要到下一个回合边界才来，详情不能因此是空的。"""
    project = tmp_path / ".claude" / "projects" / "C--code-proj"
    project.mkdir(parents=True)
    (project / f"{SID}.jsonl").write_text(_transcript_text("路径还没送到时的问题"), encoding="utf-8")

    detail = si.load_local(si.from_session("claude", {"sessionId": SID}), home=tmp_path)

    assert detail.last_prompt == "路径还没送到时的问题"
    assert si.find_transcript("../../etc", tmp_path) == "", "只按合法的会话 ID 找"
