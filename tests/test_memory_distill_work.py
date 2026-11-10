# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第三期（公司侧）——蒸馏通道：公司侧候选只交给 WSL 里的公司账号（``claude -p``），不经过个人 key。

``wsl.exe`` 与个人 key 的模型调用是替身；候选库、提案库、状态文件、服务都是真的。
"""
from __future__ import annotations

import datetime as dt
import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from pet import memory_distill as md
from pet import memory_distill_run as run
from pet import memory_distill_service as svc
from pet import memory_distill_wsl as wsl
from pet.config import Config

app = QApplication.instance() or QApplication([])

NOW = dt.datetime(2026, 11, 10, 21, 35)
WORK_SECRET = "corp-only：以后文档都按内部模板写"
WORK_RAW = json.dumps([
    {"action": "add", "scope": "global", "type": "feedback", "title": "文档按模板写", "how": "新文档先套模板",
     "evidence": ["2026-11-10 corp：以后文档都按内部模板写"]},
    {"action": "add", "scope": "project", "project": "corp", "type": "project", "title": "接口先别动",
     "evidence": ["2026-11-10 corp：这个接口先别动"]},
], ensure_ascii=False)
PERSONAL_RAW = json.dumps([{"action": "add", "scope": "global", "title": "回复用中文"}], ensure_ascii=False)


def _result(text: str, *, model: str = "claude-sonnet-5-5", is_error: bool = False, stop: str = "end_turn") -> str:
    return "login banner\n" + json.dumps({
        "type": "result", "subtype": "success", "is_error": is_error, "result": text, "num_turns": 1, "stop_reason": stop,
        "total_cost_usd": 0.12,
        "modelUsage": {model: {"inputTokens": 20, "outputTokens": 300, "cacheReadInputTokens": 1000,
                               "cacheCreationInputTokens": 80}}}, ensure_ascii=False) + "\n"


class _Wsl:
    """假的 wsl.exe：认 ``claude -p``（回一条结果 JSON）和「读记忆文件」那条（按 ``files`` 回）。"""

    def __init__(self, text: str = WORK_RAW, *, files: dict[str, str] | None = None, code: int = 0, raw: str | None = None) -> None:
        self.text, self.files, self.code, self.raw = text, files or {}, code, raw
        self.claude: list[dict] = []
        self.reads: list[str] = []

    def __call__(self, args, *, input_text=None, timeout=30.0):
        command = args[-1]
        if "claude -p" in command:
            self.claude.append({"args": list(args), "prompt": input_text, "timeout": timeout})
            if self.code:
                return self.code, ""
            return 0, self.raw if self.raw is not None else _result(self.text)
        if wsl.FILE_MARK in command:
            self.reads.append(command)
            out = []
            for path, body in self.files.items():
                if path in command:
                    out.append(f"{wsl.FILE_MARK} {path}\n{body}")
            return 0, "\n".join(out) + "\n"
        return 1, ""


# ---------------------------------------------------------------- 命令与结果


def test_claude_command_runs_headless_without_tools_or_a_saved_session():
    command = wsl.claude_command("opus", "xhigh", max_tokens=32000)
    assert command.startswith("cd ~ && BIG_FAT_FISH_HEADLESS=1 CLAUDE_CODE_MAX_OUTPUT_TOKENS=32000 claude -p --model 'opus' --effort xhigh")
    assert "--output-format json" in command and "--no-session-persistence" in command, "不留会话记录：不然蒸馏自己的提示词会被下一轮抽取抽回来"
    assert command.endswith("--max-turns 1 --tools ''"), "只要它写字，不给任何工具"
    assert "--model 'sonnet'" in wsl.claude_command("x; rm -rf ~", "bogus"), "模型名会拼进 shell：不合法就退回默认"
    assert "--effort high" in wsl.claude_command("x; rm -rf ~", "bogus")


def test_complete_sends_the_prompt_on_stdin_and_reads_the_result_record():
    runner = _Wsl("[]")
    complete = wsl.make_complete(runner)
    done = complete("提示词全文", "", None, model="opus", effort="low", timeout=300.0, max_tokens=32000)
    assert done.text == "[]" and done.model == "claude-sonnet-5-5" and done.stop_reason == "end_turn"
    assert done.input_tokens == 1100 and done.output_tokens == 300
    call = runner.claude[0]
    assert call["args"][:3] == ["-e", "bash", "-lc"] and call["prompt"] == "提示词全文"
    assert "--model 'opus' --effort low" in call["args"][3] and call["timeout"] >= 600


@pytest.mark.parametrize("runner, needle", [
    (_Wsl(code=127), "WSL"),
    (_Wsl(raw="bash: claude: command not found\n"), "command not found"),
    (_Wsl(raw=_result("Invalid API key", is_error=True)), "Invalid API key"),
    (_Wsl(raw=_result("")), ""),
])
def test_complete_turns_every_failure_into_an_error(runner, needle):
    with pytest.raises(wsl.WslError) as info:
        wsl.make_complete(runner)("p", "", None, model="sonnet", effort="high")
    assert needle in str(info.value) and str(info.value)


def test_memory_context_reads_the_wsl_claude_md_and_project_indexes_in_one_call():
    rows = [{"project": "/home/me/corp"}, {"project": "/home/me/corp/.claude/worktrees/x"}, {"project": "/home/me/other"}]
    runner = _Wsl(files={"$HOME/.claude/CLAUDE.md": "# 公司侧全局\n- 已有规矩",
                         "$HOME/.claude/projects/-home-me-corp/memory/MEMORY.md": "- [x](x.md) — corp 的索引"})
    text = wsl.memory_context(rows, runner=runner, entries_text="- 已落盘条目")
    assert len(runner.reads) == 1, "一次 wsl.exe 读完"
    assert "-home-me-other/memory/MEMORY.md" in runner.reads[0]
    assert runner.reads[0].count("-home-me-corp/memory/MEMORY.md") == 2, "worktree 归主仓库：只读一次（标签 + 路径各出现一回）"
    assert "### 全局 ~/.claude/CLAUDE.md（WSL）\n# 公司侧全局\n- 已有规矩" in text
    assert "### 已落盘的蒸馏条目\n- 已落盘条目" in text
    assert "### 项目 /home/me/corp 的 memory/MEMORY.md\n- [x](x.md) — corp 的索引" in text
    assert "/home/me/other" not in text, "没有索引的项目不列"
    assert "(空)" in wsl.memory_context([], runner=lambda *a, **k: (1, ""), entries_text="")


# ---------------------------------------------------------------- 跑一次（按侧）


def _row(text: str, n: int, *, side: str, project: str, tag: str = md.TAG_RULE) -> dict:
    return {"id": f"{side}-{n}", "time": f"2026-11-10T10:{n:02d}:00Z", "side": side, "project": project, "session_id": "s",
            "entrypoint": "cli", "branch": "main", "before": "", "text": text, "tag": tag}


ROWS = [_row("以后回复用中文", 1, side=md.SIDE_PERSONAL, project=r"C:\Users\me\Pet"),
        _row(WORK_SECRET, 2, side=md.SIDE_WORK, project="/home/me/corp"),
        _row("这个接口先别动", 3, side=md.SIDE_WORK, project="/home/me/corp")]


def test_run_once_for_the_work_side_only_sees_work_rows_and_work_rejections(tmp_path):
    store = run.ProposalStore(tmp_path)
    store.add([run.Proposal(id="p", action="add", scope="global", project="", type="feedback", title="个人侧拒过的",
                            status=run.STATUS_REJECTED),
               run.Proposal(id="w", action="add", scope="global", project="", type="feedback", title="公司侧拒过的",
                            status=run.STATUS_REJECTED, side=md.SIDE_WORK)])
    prompts: list[str] = []

    def complete(prompt, system, provider, *, model="", effort="", timeout=None, max_tokens=0):
        prompts.append(prompt)
        return SimpleNamespace(text=WORK_RAW, model="claude-sonnet-5-5", input_tokens=1, output_tokens=2)

    settings = {**md.normalize(None), "enabled": True, "model": "sonnet"}
    result, state = run.run_once(NOW, settings, ROWS, {}, None, store=store, complete=complete, memory="M",
                                 side=md.SIDE_WORK)
    assert result.ok and result.candidates == 2 and result.added == 2 and result.model == "claude-sonnet-5-5"
    assert WORK_SECRET in prompts[0] and "以后回复用中文" not in prompts[0]
    assert "- 公司侧拒过的" in prompts[0] and "个人侧拒过的" not in prompts[0]
    pending = store.pending()
    assert [p.side for p in pending] == [md.SIDE_WORK, md.SIDE_WORK] and pending[1].project == "/home/me/corp"
    assert state["last_candidate_time"] == "2026-11-10T10:03:00Z"
    assert store.dismissed_titles() == ["个人侧拒过的"] and store.dismissed_titles(md.SIDE_WORK) == ["公司侧拒过的"]
    same = run.proposal_id("add", "global", "", "文档按模板写")
    assert pending[0].id == run.proposal_id("add", "global", "", "文档按模板写", md.SIDE_WORK) != same, "两侧同名提案不撞 id"
    assert run.Proposal.from_dict({"id": "x", "title": "旧数据"}).side == md.SIDE_PERSONAL


def test_state_files_are_separate_per_side(tmp_path):
    run.save_state(tmp_path, {"done_date": "2026-11-10"})
    run.save_state(tmp_path, {"done_date": "2026-11-09"}, md.SIDE_WORK)
    assert run.load_state(tmp_path)["done_date"] == "2026-11-10"
    assert run.load_state(tmp_path, md.SIDE_WORK)["done_date"] == "2026-11-09"
    assert (tmp_path / "distill-state.json").exists() and (tmp_path / "distill-state-work.json").exists()


# ---------------------------------------------------------------- 设置


def test_work_settings_have_their_own_model_effort_time_and_prompt():
    settings = md.normalize(None)
    assert settings["work_distill"] is True and settings["work_daily_at"] == "21:30"
    assert settings["work_model"] == "sonnet" and settings["work_effort"] == "high"
    assert settings["work_prompt_zh"] == "" and settings["work_prompt_en"] == ""
    custom = md.normalize({"work_model": "opus", "work_effort": "low", "work_daily_at": "9", "work_prompt_zh": " 我的 {candidates} ",
                           "model": "claude-haiku-5-5", "effort": "xhigh", "daily_at": "20:00", "prompt_zh": "个人的"})
    assert md.normalize({"work_model": "a b; c"})["work_model"] == "sonnet", "会拼进 shell"
    view = md.side_settings(custom, md.SIDE_WORK)
    assert (view["model"], view["effort"], view["daily_at"], view["prompt_zh"]) == ("opus", "low", "09:00", "我的 {candidates}")
    assert view["enabled"] is False, "总开关没开，公司侧也不自动"
    assert md.side_settings({**custom, "enabled": True}, md.SIDE_WORK)["enabled"] is True
    assert md.side_settings({**custom, "enabled": True, "work_distill": False}, md.SIDE_WORK)["enabled"] is False
    personal = md.side_settings(custom, md.SIDE_PERSONAL)
    assert (personal["model"], personal["effort"], personal["daily_at"], personal["prompt_zh"]) == (
        "claude-haiku-5-5", "xhigh", "20:00", "个人的")


def test_settings_page_has_a_work_side_block_that_round_trips(tmp_path):
    from pet import settings_memory_distill as sd

    config = Config(tmp_path / "appdata")
    dialog = QWidget()
    dialog.config = config
    rows = sd.distill_rows(dialog)
    names = [row.objectName().removeprefix("settingRow_distill_") for row in rows]
    assert names[-6:] == ["work_distill", "work_daily_at", "work_model", "work_model_custom", "work_effort", "work_prompt"]
    assert dialog.distill_work_check.isChecked() and dialog.distill_work_model_select.currentData() == "sonnet"
    assert "{candidates}" in dialog.distill_work_prompt_editor.edit.toPlainText(), "提示词明文摆出来"
    dialog.distill_work_check.setChecked(False)
    dialog.distill_work_model_select.setCurrentIndex(dialog.distill_work_model_select.findData("opus"))
    dialog.distill_work_effort_select.setCurrentIndex(dialog.distill_work_effort_select.findData("medium"))
    dialog.distill_work_time_select.setCurrentIndex(dialog.distill_work_time_select.findData("22:00"))
    dialog.distill_work_prompt_editor.edit.setPlainText("公司侧：{candidates}")
    sd.save_distill_settings(dialog)
    saved = config.get(md.CONFIG_KEY)
    assert (saved["work_distill"], saved["work_model"], saved["work_effort"], saved["work_daily_at"]) == (False, "opus", "medium", "22:00")
    assert saved["work_prompt_zh"] == "公司侧：{candidates}" and saved["prompt_zh"] == "", "两侧提示词各存各的"
    dialog.distill_work_model_select.setCurrentIndex(dialog.distill_work_model_select.findData(sd.CUSTOM))
    dialog.distill_work_model_edit.setText("claude-opus-5-5")
    sd.save_distill_settings(dialog)
    assert config.get(md.CONFIG_KEY)["work_model"] == "claude-opus-5-5"
    dialog.deleteLater()


# ---------------------------------------------------------------- 服务


class _Personal:
    """个人 key 的替身：记下收到的每一份提示词——公司侧的字一个都不该出现在这里。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt, system, provider, *, model="", effort="", timeout=None, max_tokens=0):
        self.prompts.append(prompt)
        return SimpleNamespace(text=PERSONAL_RAW, model="claude-sonnet-5-5", input_tokens=10, output_tokens=5)


def _service(tmp_path, runner, *, now=NOW, work_distill: bool = True, spawn=lambda target: target()):
    config = Config(tmp_path / "appdata")
    config.set(md.CONFIG_KEY, {**md.normalize(None), "enabled": True, "scan_wsl": False, "work_distill": work_distill})
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("## 个人的全局记忆\n", encoding="utf-8")
    personal = _Personal()
    clock = {"now": now}
    service = svc.MemoryDistillService(
        config, spawn=spawn, roots=[], home=home, wsl_runner=runner, opener=lambda target: True,
        complete=personal.complete, provider=SimpleNamespace(model="claude-sonnet-5-5", effort="high"),
        token=lambda: "", git=lambda *a, **k: (0, ""), now=lambda: clock["now"])
    service.store.append([md.Candidate(id=r["id"], time=r["time"], side=r["side"], project=r["project"], session_id="s",
                                       entrypoint="cli", branch="main", before="", text=r["text"], tag=r["tag"])
                          for r in ROWS])
    service._clock = clock
    return service, personal, home


def test_work_distill_goes_through_wsl_and_never_reaches_the_personal_key(tmp_path):
    runner = _Wsl(files={"$HOME/.claude/CLAUDE.md": "# 公司侧全局记忆"})
    service, personal, _home = _service(tmp_path, runner)
    results = []
    service.distilled.connect(lambda result, manual: results.append(result))
    assert service.distill_now(side=md.SIDE_WORK) is True
    assert personal.prompts == [], "公司侧蒸馏不调个人 key"
    prompt = runner.claude[0]["prompt"]
    assert WORK_SECRET in prompt and "以后回复用中文" not in prompt
    assert "# 公司侧全局记忆" in prompt and "个人的全局记忆" not in prompt, "现有记忆读的是 WSL 那份"
    result = results[0]
    assert result.ok and result.side == md.SIDE_WORK and result.candidates == 2 and result.added == 2
    assert result.model == "claude-sonnet-5-5" and result.tokens_in == 1100
    assert [p.side for p in service.proposals().pending()] == [md.SIDE_WORK, md.SIDE_WORK]
    assert service.distill_state(md.SIDE_WORK)["done_date"] == "2026-11-10" and service.distill_state() == {}
    assert service.stats()["distill_work"]["last_result"]["added"] == 2

    assert service.distill_now() is True, "个人侧照旧走个人 key"
    assert len(personal.prompts) == 1 and len(runner.claude) == 1
    assert "以后回复用中文" in personal.prompts[0]
    for needle in (WORK_SECRET, "这个接口先别动", "文档按模板写", "接口先别动", "公司侧全局记忆"):
        assert needle not in personal.prompts[0], f"公司侧的字进了个人 key：{needle}"


def test_work_rejections_and_entries_stay_out_of_the_personal_prompt(tmp_path):
    runner = _Wsl()
    service, personal, _home = _service(tmp_path, runner)
    service.distill_now(side=md.SIDE_WORK)
    first = service.proposals().pending()[0]
    assert service.review(first.id, run.STATUS_REJECTED) is None
    service.distill_now()
    assert "文档按模板写" not in personal.prompts[0], "公司侧拒掉的标题不进个人侧的「别再提」"


def test_work_distill_failure_is_reported_on_the_work_side_only(tmp_path):
    service, personal, _home = _service(tmp_path, _Wsl(code=127))
    results = []
    service.distilled.connect(lambda result, manual: results.append(result))
    service.distill_now(side=md.SIDE_WORK)
    assert not results[0].ok and results[0].side == md.SIDE_WORK and "WSL" in results[0].error
    assert service.distill_state(md.SIDE_WORK)["attempts"] == 1 and "done_date" not in service.distill_state(md.SIDE_WORK)
    assert service.stats()["distill"]["last_error"] == "" and service.stats()["distill_work"]["last_error"]
    assert personal.prompts == []


def test_daily_check_distills_each_side_on_its_own_clock(tmp_path):
    runner = _Wsl()
    service, personal, _home = _service(tmp_path, runner, now=NOW.replace(hour=20))
    service._config.set(md.CONFIG_KEY, {**service.settings(), "work_daily_at": "22:00"})
    service._clock["now"] = NOW                       # 21:35：个人侧到点，公司侧没到
    service.check()
    assert len(personal.prompts) == 1 and runner.claude == []
    service._clock["now"] = NOW.replace(hour=22, minute=5)
    service.check()
    assert len(personal.prompts) == 1 and len(runner.claude) == 1
    service.check()
    assert len(runner.claude) == 1, "今天做过了"


def test_both_sides_and_an_extraction_can_overlap_without_losing_anyones_result(tmp_path):
    """三个后台线程交叠着跑（真机上蒸馏要几分钟，每小时的抽取会撞上）：谁的结果都不能被当成「过期的」丢掉——
    丢了的话那一项的「忙」标记永远不清，之后再也触发不了。"""
    queued: list = []
    service, personal, _home = _service(tmp_path, _Wsl(), spawn=queued.append)
    got: list[str] = []
    service.distilled.connect(lambda result, manual: got.append(result.side))
    service.refreshed.connect(lambda added: got.append("refresh"))
    assert service.distill_now(side=md.SIDE_WORK) and service.refresh_now() and service.distill_now()
    assert service.distill_now(side=md.SIDE_WORK) is False, "同一侧忙着不叠加"
    assert service.is_distilling(md.SIDE_WORK) and service.is_distilling(md.SIDE_PERSONAL) and service.busy
    for target in queued:
        target()
    assert got == [md.SIDE_WORK, "refresh", md.SIDE_PERSONAL]
    assert not service.distilling and not service.busy
    stale: list = []
    service._spawn = stale.append
    service.distill_now(side=md.SIDE_WORK)
    service.stop()
    stale[0]()
    assert got == [md.SIDE_WORK, "refresh", md.SIDE_PERSONAL], "停了之后才回来的结果不要"


def test_work_side_can_be_switched_off(tmp_path):
    runner = _Wsl()
    service, _personal, _home = _service(tmp_path, runner, work_distill=False)
    service.check()
    assert runner.claude == []
    assert service.distill_now(side=md.SIDE_WORK) is True and len(runner.claude) == 1, "手动仍然可以"
