# -*- coding: utf-8 -*-
"""最近的对话（纯逻辑）：记下每个 Claude Code 会话在哪打开的，回头还找得到。

Claude Code 的对话记录集中存在 ``~/.claude/projects/<目录编码>/<会话ID>.jsonl``，
但 ``claude --resume`` 只列当前目录的会话——忘了目录就没有入口。这里的规则：

- 一个会话一行（同一个会话昨天开过今天又开 = 更新成今天）；
- 最多留 7 天、30 条（可配置）；
- 同一个目录的三种写法（``C:\\…`` / ``c:\\…`` / ``/c/…``）归一成一种；
- 只存路径、标题这些，不存对话内容。
"""

from __future__ import annotations

import json
import os

import pytest

from pet import claude_session_history as hist
from pet.claude_session_history import SessionHistory

DAY = 86400.0
SID_A = "11111111-aaaa-4bbb-8ccc-000000000001"
SID_B = "22222222-aaaa-4bbb-8ccc-000000000002"
SID_C = "33333333-aaaa-4bbb-8ccc-000000000003"


class Clock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _history(tmp_path=None, **kwargs):
    clock = kwargs.pop("clock", None) or Clock()
    history = SessionHistory(None if tmp_path is None else tmp_path / "history.json", clock=clock, **kwargs)
    history.clock = clock
    return history


# ---------------------------------------------------------------- 路径归一

@pytest.mark.parametrize("raw, expected", [
    ("C:\\Users\\limin\\Github\\dsh-pet", "C:\\Users\\limin\\Github\\dsh-pet"),
    ("c:\\Users\\limin\\Github\\dsh-pet", "C:\\Users\\limin\\Github\\dsh-pet"),
    ("/c/Users/limin/Github/dsh-pet", "C:\\Users\\limin\\Github\\dsh-pet"),
    ("C:/Users/limin/Github/dsh-pet/", "C:\\Users\\limin\\Github\\dsh-pet"),
    ("D:\\", "D:\\"),
    ("", ""),
])
def test_windows_paths_are_normalised_to_one_spelling(raw, expected):
    assert hist.normalize_cwd("claude", raw) == expected


def test_wsl_paths_stay_posix():
    assert hist.normalize_cwd("claude_wsl", "/home/limin/work/") == "/home/limin/work"
    assert hist.normalize_cwd("claude_wsl", "/") == "/"
    assert hist.normalize_cwd("claude_wsl", "/c/Users/limin") == "/c/Users/limin", "WSL 里 /c/ 就是个普通目录"


# ---------------------------------------------------------------- 记录规则

def test_one_row_per_session_and_reopening_refreshes_it():
    history = _history()
    history.record("claude", SID_A, cwd="C:\\work\\api", title="Fix login loop")
    history.clock.now += DAY
    history.record("claude", SID_A, cwd="c:\\work\\api", title="Fix login loop (done)")

    (entry,) = history.entries()
    assert entry.title == "Fix login loop (done)"
    assert entry.cwd == "C:\\work\\api"
    assert entry.last_seen == history.clock.now, "昨天那条就地更新成今天，不留两行"


def test_two_sessions_in_the_same_folder_are_two_rows():
    history = _history()
    history.record("claude", SID_A, cwd="C:\\work\\api", title="first")
    history.clock.now += 60
    history.record("claude", SID_B, cwd="C:\\work\\api", title="second")
    assert [e.title for e in history.entries()] == ["second", "first"], "新的在前"


def test_same_session_id_on_both_channels_is_kept_apart():
    history = _history()
    history.record("claude", SID_A, cwd="C:\\work")
    history.record("claude_wsl", SID_A, cwd="/home/limin/work")
    assert len(history.entries()) == 2


def test_blank_fields_never_erase_what_is_known():
    history = _history()
    history.record("claude", SID_A, cwd="C:\\work", title="T", entrypoint="cli", git_branch="main")
    history.record("claude", SID_A)          # 后来的一条更新什么都没带
    (entry,) = history.entries()
    assert (entry.cwd, entry.title, entry.entrypoint, entry.git_branch) == ("C:\\work", "T", "cli", "main")


def test_a_session_without_a_known_folder_is_not_listed_yet():
    """刚出场时 hook 还没送来目录：先记着，知道目录了再出现在列表里。"""
    history = _history()
    history.record("claude", SID_A, title="T")
    assert history.entries() == []
    history.record("claude", SID_A, cwd="C:\\work")
    assert [e.title for e in history.entries()] == ["T"]


def test_bad_session_ids_are_refused():
    history = _history()
    assert history.record("claude", "", cwd="C:\\x") is False
    assert history.record("claude", "a b; rm -rf /", cwd="C:\\x") is False, "ID 之后要拼进命令行"
    assert history.entries() == []


def test_older_scan_results_do_not_move_a_row_back_in_time():
    history = _history()
    history.record("claude", SID_A, cwd="C:\\work")
    live = history.clock.now
    history.record("claude", SID_A, cwd="C:\\work", seen=live - 3600)      # 回填读到的是文件修改时间
    assert history.entries()[0].last_seen == live


# ---------------------------------------------------------------- 上限

def test_entries_older_than_a_week_drop_out():
    history = _history()
    history.record("claude", SID_A, cwd="C:\\old")
    history.clock.now += 6 * DAY
    history.record("claude", SID_B, cwd="C:\\new")
    assert len(history.entries()) == 2
    history.clock.now += 1.5 * DAY
    assert [e.cwd for e in history.entries()] == ["C:\\new"]


def test_only_the_newest_entries_are_kept_beyond_the_cap():
    history = _history(max_entries=3)
    for index in range(5):
        history.clock.now += 60
        history.record("claude", f"{index:08d}-aaaa-4bbb-8ccc-000000000000", cwd=f"C:\\p{index}")
    assert [e.cwd for e in history.entries()] == ["C:\\p4", "C:\\p3", "C:\\p2"]


def test_limits_can_be_changed_later_and_are_clamped():
    history = _history()
    history.configure(max_age_days=0, max_entries=10_000)
    assert history.max_age_days == 1 and history.max_entries == 200
    history.configure(max_age_days="x", max_entries=None)
    assert (history.max_age_days, history.max_entries) == (7, 30)


# ---------------------------------------------------------------- 何时值得落盘

def test_record_reports_whether_anything_worth_saving_changed():
    history = _history()
    assert history.record("claude", SID_A, cwd="C:\\work", title="T") is True
    history.clock.now += 5
    assert history.record("claude", SID_A, cwd="C:\\work", title="T") is False, "每次工具调用都来一条：不为几秒的时间差写盘"
    history.clock.now += 120
    assert history.record("claude", SID_A, cwd="C:\\work", title="T") is True
    assert history.record("claude", SID_A, title="T2") is True


def test_remove_and_clear():
    history = _history()
    history.record("claude", SID_A, cwd="C:\\a")
    history.record("claude", SID_B, cwd="C:\\b")
    assert history.remove(("claude", SID_A)) is True
    assert history.remove(("claude", SID_A)) is False
    assert [e.cwd for e in history.entries()] == ["C:\\b"]
    assert history.clear() is True and history.entries() == []


# ---------------------------------------------------------------- 落盘

def test_round_trip_through_disk(tmp_path):
    history = _history(tmp_path)
    history.record("claude", SID_A, cwd="C:\\work\\api", title="Fix login loop", entrypoint="cli", git_branch="main")
    history.record("claude_wsl", SID_B, cwd="/home/limin/work", distro="Ubuntu", entrypoint="claude-vscode")
    history.ui_open = True
    assert history.save() is True

    again = _history(tmp_path, clock=history.clock)
    again.load()
    assert [(e.agent, e.session_id, e.cwd, e.title, e.entrypoint, e.git_branch, e.distro)
            for e in again.entries()] == [
        (e.agent, e.session_id, e.cwd, e.title, e.entrypoint, e.git_branch, e.distro)
        for e in history.entries()]
    assert again.ui_open is True, "折叠框开着还是合着也记住"


def test_file_holds_paths_and_titles_only(tmp_path):
    history = _history(tmp_path)
    history.record("claude", SID_A, cwd="C:\\work", title="T")
    history.save()
    data = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert set(data["entries"][0]) == {
        "agent", "session_id", "cwd", "title", "project", "entrypoint", "git_branch", "distro", "last_seen"}


@pytest.mark.parametrize("content", ["", "not json", "[]", '{"entries": "x"}', '{"entries": [1, {"agent": 5}]}'])
def test_damaged_file_loads_as_empty(tmp_path, content):
    (tmp_path / "history.json").write_text(content, encoding="utf-8")
    history = _history(tmp_path)
    history.load()
    assert history.entries() == []


def test_expired_entries_are_not_written_back(tmp_path):
    history = _history(tmp_path)
    history.record("claude", SID_A, cwd="C:\\old")
    history.clock.now += 8 * DAY
    history.record("claude", SID_B, cwd="C:\\new")
    history.save()
    data = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert [e["cwd"] for e in data["entries"]] == ["C:\\new"]


# ---------------------------------------------------------------- 显示用的小东西

def test_label_prefers_title_then_folder_then_short_id():
    history = _history()
    history.record("claude", SID_A, cwd="C:\\work\\api", title="Fix login loop")
    history.record("claude", SID_B, cwd="C:\\work\\api")
    history.record("claude_wsl", SID_C, cwd="/")
    by_id = {e.session_id: e for e in history.entries()}
    assert by_id[SID_A].label == "Fix login loop"
    assert by_id[SID_B].label == "api" and by_id[SID_B].folder == "api"
    assert by_id[SID_C].label == SID_C[:8]


@pytest.mark.parametrize("seconds, text", [
    (5, "刚刚"), (59, "刚刚"), (60, "1 分钟前"), (3599, "59 分钟前"), (3600, "1 小时前"),
    (86399, "23 小时前"), (86400, "昨天"), (2 * 86400, "2 天前"), (6.9 * 86400, "6 天前"),
])
def test_ago_text(seconds, text):
    assert hist.ago_text(seconds) == text


def test_where_text_says_how_it_was_opened():
    history = _history()
    history.record("claude", SID_A, cwd="C:\\a", entrypoint="cli")
    history.record("claude", SID_B, cwd="C:\\b", entrypoint="claude-vscode")
    history.record("claude_wsl", SID_C, cwd="/c", entrypoint="cli", distro="Ubuntu")
    by_id = {e.session_id: e for e in history.entries()}
    assert by_id[SID_A].where == "终端"
    assert by_id[SID_B].where == "VS Code"
    assert by_id[SID_C].where == "终端 · WSL"


# ---------------------------------------------------------------- 回填：本机

def _transcript(folder, session_id, lines, *, mtime: float) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session_id}.jsonl"
    path.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n", encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_scan_finds_recent_transcripts_with_where_they_were_opened(tmp_path):
    now = 1_800_000_000.0
    projects = tmp_path / ".claude" / "projects"
    _transcript(projects / "C--work-api", SID_A, [
        {"type": "queue-operation", "sessionId": SID_A},
        {"type": "user", "cwd": "C:\\work\\api", "gitBranch": "main", "entrypoint": "cli"},
        {"type": "assistant", "cwd": "/c/work/api/sub"},            # 会话中途 cd 过
        {"type": "ai-title", "aiTitle": "Fix login loop"},
    ], mtime=now - 3600)
    _transcript(projects / "C--old", SID_B, [{"type": "user", "cwd": "C:\\old"}], mtime=now - 9 * DAY)
    _transcript(projects / "C--work-api", "agent-a1b2c3", [{"type": "user", "cwd": "C:\\x"}], mtime=now)
    (projects / "C--work-api" / "memory").mkdir()

    found = hist.scan_local(tmp_path, now=now)

    assert found == [{
        "agent": "claude", "session_id": SID_A, "cwd": "C:\\work\\api", "title": "Fix login loop",
        "git_branch": "main", "entrypoint": "cli", "seen": now - 3600,
    }], "只要 7 天内的、文件名是会话 ID 的；目录取会话开头那一条（它就是能 --resume 的那个目录）"


def test_scan_survives_garbage(tmp_path):
    projects = tmp_path / ".claude" / "projects" / "p"
    projects.mkdir(parents=True)
    (projects / f"{SID_A}.jsonl").write_bytes(b"\xff\xfe not json at all\n{broken")
    (projects / f"{SID_B}.jsonl").write_text("", encoding="utf-8")
    assert hist.scan_local(tmp_path, now=os.path.getmtime(projects / f"{SID_A}.jsonl")) == []
    assert hist.scan_local(tmp_path / "nowhere") == []


def test_scan_reads_only_the_ends_of_huge_transcripts(tmp_path):
    now = 1_800_000_000.0
    projects = tmp_path / ".claude" / "projects" / "p"
    filler = {"type": "assistant", "message": "x" * 4000}
    _transcript(projects, SID_A, [
        {"type": "user", "cwd": "C:\\work\\big", "entrypoint": "claude-vscode"},
        *([filler] * 400),
        {"type": "ai-title", "aiTitle": "Big one"},
    ], mtime=now)
    (found,) = hist.scan_local(tmp_path, now=now)
    assert (found["cwd"], found["title"], found["entrypoint"]) == ("C:\\work\\big", "Big one", "claude-vscode")


# ---------------------------------------------------------------- 回填：WSL

def test_wsl_scan_output_is_parsed():
    head_a = json.dumps({"type": "user", "cwd": "/home/limin/work", "entrypoint": "cli", "gitBranch": "dev"})
    tail_a = json.dumps({"type": "ai-title", "aiTitle": "WSL chat"})
    text = "\n".join([
        "@@distro Ubuntu-24.04",
        f"@@file 1799990000.5 /home/limin/.claude/projects/-home-limin-work/{SID_A}.jsonl",
        head_a, "@@tail", "{cut-off line", tail_a, "@@end",
        "@@file 1799980000 /home/limin/.claude/projects/-x/agent-zz.jsonl", "{}", "@@tail", "{}", "@@end",
        f"@@file nonsense /home/limin/.claude/projects/-y/{SID_B}.jsonl", "{}", "@@tail", "{}", "@@end",
    ])
    assert hist.parse_wsl_scan(text) == [{
        "agent": "claude_wsl", "session_id": SID_A, "cwd": "/home/limin/work", "title": "WSL chat",
        "git_branch": "dev", "entrypoint": "cli", "distro": "Ubuntu-24.04", "seen": 1799990000.5,
    }]


def test_wsl_scan_runs_one_command_and_tolerates_failure():
    calls = []

    def runner(args, **_kwargs):
        calls.append(args)
        return 1, ""

    assert hist.scan_wsl(runner=runner, max_age_days=7) == []
    assert len(calls) == 1 and calls[0][:3] == ["-e", "sh", "-c"]
    assert calls[0][-1] == "7", "天数作为参数传进去，不拼进脚本"


# ---------------------------------------------------------------- 恢复命令

def _which(found: dict):
    return lambda name: found.get(name)


def _entry(agent="claude", **fields):
    history = _history()
    history.record(agent, SID_A, **fields)
    return history.entries()[0]


def test_terminal_resume_opens_windows_terminal_in_the_folder():
    argv = hist.terminal_resume_argv(_entry(cwd="C:\\work\\my api"), which=_which({"wt": "C:\\wt.exe"}))
    assert argv == ["C:\\wt.exe", "-d", "C:\\work\\my api", "cmd", "/k", "claude", "--resume", SID_A]


def test_terminal_resume_falls_back_to_a_plain_console():
    argv = hist.terminal_resume_argv(_entry(cwd="C:\\work"), which=_which({}))
    assert argv == ["cmd", "/c", "start", "", "/D", "C:\\work", "cmd", "/k", "claude", "--resume", SID_A]


def test_terminal_resume_for_wsl_enters_the_distro_in_that_folder():
    entry = _entry("claude_wsl", cwd="/home/limin/work", distro="Ubuntu")
    argv = hist.terminal_resume_argv(entry, which=_which({"wt": "C:\\wt.exe"}), wsl="C:\\wsl.exe")
    assert argv == ["C:\\wt.exe", "C:\\wsl.exe", "-d", "Ubuntu", "--cd", "/home/limin/work", "--",
                    "bash", "-lic", f"claude --resume {SID_A}; exec bash"]
    assert hist.terminal_resume_argv(entry, which=_which({}), wsl="") is None, "没有 wsl.exe 就恢复不了"


def test_default_action_follows_how_the_session_was_opened():
    assert hist.default_action(_entry(cwd="C:\\a", entrypoint="cli")) == "terminal"
    assert hist.default_action(_entry(cwd="C:\\a", entrypoint="claude-vscode")) == "vscode"
    assert hist.default_action(_entry(cwd="C:\\a")) == "terminal", "不知道从哪开的：按终端"
