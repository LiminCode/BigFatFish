# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第三期（公司侧）——落盘：接受了的公司侧提案写进 WSL 里的 CLAUDE.md 受管块 / 项目 memory，
不碰个人侧的任何文件。

WSL 的文件系统是替身（一个按路径存内容的假 ``wsl.exe``）；条目库、备份目录、提案库、服务、窗口是真的。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pet import i18n
from pet import memory_distill as md
from pet import memory_distill_run as run
from pet import memory_distill_service as svc
from pet import memory_distill_sink as sink
from pet import memory_distill_ui as ui
from pet import memory_distill_wsl_sink as wsink
from pet.config import Config

app = QApplication.instance() or QApplication([])

NOW = dt.datetime(2026, 11, 10, 21, 35)
CLAUDE_MD = "$HOME/.claude/CLAUDE.md"
CORP_MEMORY = "$HOME/.claude/projects/-home-me-corp/memory"
ORIGINAL = "# 公司侧手写的全局记忆\r\n- 这一行是 CRLF\n- 这一行是 LF\n"


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


class _WslFs:
    """假的 wsl.exe：只认 ``memory_distill_wsl_sink`` 发的读 / 写 / 删三种命令，文件存在 ``files`` 里。"""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files = dict(files or {})
        self.fail_reads = self.fail_writes = False
        self.ops: list[tuple[str, str]] = []
        self.other: list[list[str]] = []

    def __call__(self, args, *, input_text=None, timeout=30.0):
        command = args[-1]
        match = re.search(r'f="([^"]+)"', command)
        if args[:3] != ["-e", "sh", "-c"] or match is None:
            self.other.append(list(args))
            return 1, ""
        path = match.group(1)
        if "rm -f" in command:
            self.ops.append(("rm", path))
            self.files.pop(path, None)
            return 0, ""
        if 'cat > "$t"' in command:
            self.ops.append(("write", path))
            if self.fail_writes:
                return 1, ""
            self.files[path] = input_text
            return 0, ""
        self.ops.append(("read", path))
        if self.fail_reads:
            return 1, ""
        return 0, self.files.get(path, wsink.MISSING)

    def written(self) -> list[str]:
        return [path for op, path in self.ops if op == "write"]


def _proposal(action: str, scope: str, title: str, *, project: str = "", replaces: str = "", how: str = "照做") -> run.Proposal:
    return run.Proposal(id=run.proposal_id(action, scope, project, title, md.SIDE_WORK), action=action, scope=scope,
                        project=project, type="feedback", title=title, why="因为说过", how=how,
                        evidence=["2026-11-10 corp：原话"], replaces=replaces, side=md.SIDE_WORK)


# ---------------------------------------------------------------- 读写 WSL 里的文件


def test_paths_outside_the_claude_home_are_refused():
    fs = _WslFs()
    assert wsink.read_text("/etc/passwd", fs) is None and wsink.write_text("$HOME/.claude/x; rm -rf ~", "x", fs) is False
    assert wsink.remove('$HOME/.claude/a"b', fs) is False and wsink.write_text("$HOME/.ssh/config", "x", fs) is False
    assert wsink.read_text("$HOME/.claude/../.ssh/id", fs) is None
    assert fs.ops == [] and fs.other == [], "不合规矩的路径连 wsl.exe 都不调"


def test_read_tells_missing_from_failed_and_refuses_undecodable_text():
    fs = _WslFs({CLAUDE_MD: ORIGINAL})
    assert wsink.read_text(CLAUDE_MD, fs) == ORIGINAL
    assert wsink.read_text("$HOME/.claude/none.md", fs) == "", "文件不存在 = 空"
    fs.fail_reads = True
    assert wsink.read_text(CLAUDE_MD, fs) is None, "问不到 ≠ 空：不能当成空文件再写回去"
    assert wsink.read_text(CLAUDE_MD, _WslFs({CLAUDE_MD: "坏字节 \ufffd"})) is None, "解不出来的字节写回去会把原文改掉"


# ---------------------------------------------------------------- 一条提案落到 WSL


def test_global_entry_goes_into_the_managed_block_of_the_wsl_claude_md(tmp_path):
    fs = _WslFs({CLAUDE_MD: ORIGINAL})
    entries = sink.EntriesStore(tmp_path, md.SIDE_WORK)
    applied = wsink.apply_proposal(_proposal("add", "global", "文档按模板写"), NOW, entries=entries, runner=fs,
                                   backup_dir=tmp_path / "backups")
    assert applied.error == "" and applied.claude_md and applied.project_file == "" and not applied.vault_written
    text = fs.files[CLAUDE_MD]
    assert text.startswith(ORIGINAL + "\n" + sink.BLOCK_START), "块外逐字不动（连 CRLF 那行）"
    assert "- **文档按模板写** — 照做" in text and text.rstrip().endswith(sink.BLOCK_END)
    backups = list((tmp_path / "backups").glob("CLAUDE.md.wsl.*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == ORIGINAL.encode("utf-8"), "改前整份备份（在本机）"
    assert [e.title for e in entries.load()] == ["文档按模板写"]
    assert entries.path.name == "entries-work.json" and not (tmp_path / "entries.json").exists(), "不进个人侧的条目库"

    second = wsink.apply_proposal(_proposal("add", "global", "提交信息用英文"), NOW, entries=entries, runner=fs,
                                  backup_dir=tmp_path / "backups")
    assert second.claude_md and fs.files[CLAUDE_MD].count(sink.BLOCK_START) == 1, "原位替换，不追加第二块"
    assert fs.files[CLAUDE_MD].startswith(ORIGINAL + "\n" + sink.BLOCK_START)
    assert "- **文档按模板写**" in fs.files[CLAUDE_MD] and "- **提交信息用英文**" in fs.files[CLAUDE_MD]
    assert backups[0].read_bytes() == ORIGINAL.encode("utf-8"), "同一秒里再改一次，不能把更早的那份备份盖掉"


def test_project_entry_gets_its_own_memory_file_and_an_index_line(tmp_path):
    index = "- [手写的](hand.md) — 留着\n"
    fs = _WslFs({f"{CORP_MEMORY}/MEMORY.md": index})
    entries = sink.EntriesStore(tmp_path, md.SIDE_WORK)
    proposal = _proposal("add", "project", "接口先别动", project="/home/me/corp/.claude/worktrees/w1")
    applied = wsink.apply_proposal(proposal, NOW, entries=entries, runner=fs, backup_dir=tmp_path / "backups")
    path = f"{CORP_MEMORY}/distill-{proposal.id}.md"
    assert applied.error == "" and applied.project_file == path and not applied.claude_md, "worktree 归主仓库"
    assert fs.files[path].startswith(f"---\nname: distill-{proposal.id}\n") and "**How to apply:** 照做" in fs.files[path]
    assert fs.files[f"{CORP_MEMORY}/MEMORY.md"] == index + f"- [接口先别动](distill-{proposal.id}.md) — 照做\n"
    assert CLAUDE_MD not in fs.files and fs.written() == [path, f"{CORP_MEMORY}/MEMORY.md"]


def test_change_and_retire_rewrite_in_place(tmp_path):
    fs = _WslFs({CLAUDE_MD: ORIGINAL})
    entries = sink.EntriesStore(tmp_path, md.SIDE_WORK)
    kwargs = {"entries": entries, "runner": fs, "backup_dir": tmp_path / "backups"}
    wsink.apply_proposal(_proposal("add", "global", "文档按模板写"), NOW, **kwargs)
    project = _proposal("add", "project", "接口先别动", project="/home/me/corp")
    wsink.apply_proposal(project, NOW, **kwargs)
    changed = wsink.apply_proposal(_proposal("change", "global", "文档按新模板写", replaces="文档按模板写", how="用 v2"), NOW, **kwargs)
    assert changed.claude_md and "- **文档按新模板写** — 用 v2" in fs.files[CLAUDE_MD] and "文档按模板写**" not in fs.files[CLAUDE_MD]
    retired = wsink.apply_proposal(_proposal("retire", "project", "接口先别动", project="/home/me/corp"), NOW, **kwargs)
    assert retired.removed and f"{CORP_MEMORY}/distill-{project.id}.md" not in fs.files
    assert fs.files[f"{CORP_MEMORY}/MEMORY.md"].strip() == "", "索引行也拿掉"
    missing = wsink.apply_proposal(_proposal("retire", "global", "从没写过的"), NOW, **kwargs)
    assert missing.error and "从没写过的" in missing.error
    assert [(e.title, e.retired) for e in entries.load()] == [("文档按新模板写", False), ("接口先别动", True)]


@pytest.mark.parametrize("broken", ["fail_reads", "fail_writes"])
def test_a_wsl_failure_writes_nothing_and_rolls_the_entry_back(tmp_path, broken):
    fs = _WslFs({CLAUDE_MD: ORIGINAL})
    setattr(fs, broken, True)
    entries = sink.EntriesStore(tmp_path, md.SIDE_WORK)
    applied = wsink.apply_proposal(_proposal("add", "global", "文档按模板写"), NOW, entries=entries, runner=fs,
                                   backup_dir=tmp_path / "backups")
    assert applied.error and not applied.claude_md and fs.files[CLAUDE_MD] == ORIGINAL
    assert entries.load() == [], "没落成就不留条目：再接受一次不会多出一条重复的"


# ---------------------------------------------------------------- 服务与页面


WORK_RAW = json.dumps([
    {"action": "add", "scope": "global", "type": "feedback", "title": "文档按模板写", "how": "新文档先套模板",
     "evidence": ["2026-11-10 corp：原话"]},
    {"action": "add", "scope": "project", "project": "corp", "type": "project", "title": "接口先别动",
     "evidence": ["2026-11-10 corp：原话"]},
], ensure_ascii=False)
PERSONAL_RAW = json.dumps([{"action": "add", "scope": "global", "title": "回复用中文", "how": "解释用中文"}], ensure_ascii=False)


class _Wsl(_WslFs):
    """文件系统 + ``claude -p`` + 列清单都认的假 wsl.exe。"""

    def __init__(self, files=None) -> None:
        super().__init__(files)
        self.claude: list[str] = []

    def __call__(self, args, *, input_text=None, timeout=30.0):
        command = args[-1]
        if "claude -p" in command:
            self.claude.append(input_text)
            return 0, json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": WORK_RAW,
                                  "stop_reason": "end_turn", "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 5, "outputTokens": 7}}})
        return super().__call__(args, input_text=input_text, timeout=timeout)


class _Host:
    sprite = None

    def __init__(self) -> None:
        self.bubbles: list[str] = []

    def show_bubble(self, text: str, _ms: int) -> None:
        self.bubbles.append(text)

    def open_settings_for(self, _sprite) -> None:
        pass


def _row(text: str, n: int, side: str, project: str) -> md.Candidate:
    return md.Candidate(id=f"{side}-{n}", time=f"2026-11-10T10:{n:02d}:00Z", side=side, project=project, session_id="s",
                        entrypoint="cli", branch="main", before="", text=text, tag=md.TAG_RULE)


def _service(tmp_path, runner, *, spawn=lambda target: target()):
    config = Config(tmp_path / "appdata")
    config.set(md.CONFIG_KEY, {**md.normalize(None), "enabled": True, "scan_wsl": False})
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("## 个人的全局记忆\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    config.set("personal", {"repo_dir": str(vault)})
    git_calls: list = []

    def personal(prompt, system, provider, *, model="", effort="", timeout=None, max_tokens=0):
        return SimpleNamespace(text=PERSONAL_RAW, model="claude-sonnet-5-5", input_tokens=10, output_tokens=5)

    service = svc.MemoryDistillService(
        config, spawn=spawn, roots=[tmp_path / "no-transcripts"], home=home, wsl_runner=runner, opener=lambda target: True, complete=personal,
        provider=SimpleNamespace(model="claude-sonnet-5-5", effort="high"), token=lambda: "",
        git=lambda repo, args, **k: git_calls.append(list(args)) or (0, ""), now=lambda: NOW)
    service.store.append([_row("以后回复用中文", 1, md.SIDE_PERSONAL, r"C:\Users\me\Pet"),
                          _row("以后文档都按模板写", 2, md.SIDE_WORK, "/home/me/corp")])
    service._git_calls = git_calls
    return service, home, vault


def test_accepting_a_work_proposal_writes_wsl_and_leaves_every_personal_target_alone(tmp_path):
    runner = _Wsl({CLAUDE_MD: ORIGINAL})
    service, home, vault = _service(tmp_path, runner)
    service.distill_now(side=md.SIDE_WORK)
    first, second = service.proposals().pending()
    reviewed: list = []
    service.reviewed.connect(lambda pid, applied: reviewed.append((pid, applied)))
    service.review(first.id, run.STATUS_ACCEPTED, title="文档一律按模板写")
    pid, applied = reviewed[0]
    assert pid == first.id and applied.error == "" and applied.claude_md
    assert "- **文档一律按模板写** — 新文档先套模板" in runner.files[CLAUDE_MD] and runner.files[CLAUDE_MD].startswith(ORIGINAL)
    service.review(second.id, run.STATUS_ACCEPTED)
    assert reviewed[1][1].project_file == f"{CORP_MEMORY}/distill-{second.id}.md"
    assert (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8") == "## 个人的全局记忆\n", "个人侧的 CLAUDE.md 不动"
    assert not (home / ".claude" / "projects").exists() and list(vault.iterdir()) == [] and service._git_calls == [], \
        "个人侧的项目 memory、个人知识库、个人仓库的 git 都不碰"
    assert service.entries().load() == [] and [e.title for e in service.entries(md.SIDE_WORK).load()] == ["文档一律按模板写", "接口先别动"]
    assert service.proposals().counts()["accepted"] == 2 and service.proposals().pending() == []
    stats = service.stats()
    assert stats["entries"] == {"global": 0, "project": 0, "retired": 0}
    assert stats["entries_work"] == {"global": 1, "project": 1, "retired": 0}


def test_work_review_runs_off_the_gui_thread_and_a_failure_keeps_the_proposal_pending(tmp_path):
    queued: list = []
    runner = _Wsl({CLAUDE_MD: ORIGINAL})
    service, _home, _vault = _service(tmp_path, runner)
    service.distill_now(side=md.SIDE_WORK)
    first = service.proposals().pending()[0]
    service._spawn = queued.append
    reviewed: list = []
    service.reviewed.connect(lambda pid, applied: reviewed.append(applied))
    assert service.review(first.id, run.STATUS_ACCEPTED) is None
    assert len(queued) == 1 and reviewed == [] and runner.written() == [], "写 WSL 要起 wsl.exe（冷启动几秒），不在 GUI 线程里等"
    assert service.review(first.id, run.STATUS_ACCEPTED) is None and len(queued) == 1, "这条正在写，不叠加"
    runner.fail_writes = True
    queued.pop()()
    assert reviewed[0].error and service.proposals().get(first.id).status == run.STATUS_PENDING
    assert service.entries(md.SIDE_WORK).load() == [] and runner.files[CLAUDE_MD] == ORIGINAL
    runner.fail_writes = False
    service.review(first.id, run.STATUS_ACCEPTED)
    queued.pop()()
    assert reviewed[1].error == "" and service.proposals().get(first.id).status == run.STATUS_ACCEPTED


def test_personal_entries_still_go_to_the_personal_claude_md_only(tmp_path):
    runner = _Wsl({CLAUDE_MD: ORIGINAL})
    service, home, _vault = _service(tmp_path, runner)
    service.distill_now()
    first = service.proposals().pending()[0]
    applied = service.review(first.id, run.STATUS_ACCEPTED)
    assert applied.claude_md and "- **回复用中文**" in (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert runner.ops == [] and runner.files[CLAUDE_MD] == ORIGINAL, "个人侧的条目不写进 WSL"


def test_page_tells_the_sides_apart_and_has_a_work_side_button(tmp_path):
    runner = _Wsl({CLAUDE_MD: ORIGINAL})
    service, _home, _vault = _service(tmp_path, runner)
    controller = ui.MemoryDistillController(_Host(), service)
    controller.open_window()
    window = controller.window
    try:
        assert window.distill_btn.text() == "现在总结" and window.distill_work_btn.text() == "总结公司侧"
        window.distill_work_btn.click()
        assert len(runner.claude) == 1 and window.tabs.currentIndex() == 2
        assert window.status_label.text() == "公司侧 · 总结完成：1 条候选 → 2 条提案，新增 2 条待审"
        window.distill_btn.click()
        labels = [window.proposal_list.item(i).text() for i in range(window.proposal_list.count())]
        assert labels == ["公司 · 新增 · 全局 · 文档按模板写", "公司 · 新增 · corp · 接口先别动", "新增 · 全局 · 回复用中文"]
        lines = window.run_label.text().split("\n")
        assert lines[0].startswith("上次总结 2026-11-10 21:35 · claude-sonnet-5-5") and lines[1].startswith("公司侧 · 上次总结 2026-11-10 21:35")
        window.proposal_list.setCurrentRow(0)
        assert window.proposal_head.text().startswith("公司侧（写进 WSL） · 新增 · 全局")
        window.accept_btn.click()
        assert window.review_status.text() == "已写入：WSL 里的 CLAUDE.md 受管块"
        window.proposal_list.setCurrentRow(0)
        window.accept_btn.click()
        assert window.review_status.text() == "已写入：WSL 里的项目 memory"
        assert window.proposal_list.count() == 1 and window.proposal_head.text().startswith("新增 · 全局")
        assert window.diagram.value("sink") == "全局 0 条 · 项目 0 条 · 公司侧 2 条"
        i18n.set_language("en")
        assert ui.proposal_label(service.proposals().load()[0]).startswith("work · add · global · ")
    finally:
        window.close()
        window.deleteLater()
