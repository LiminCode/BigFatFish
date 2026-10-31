# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第二期的 Qt 侧：服务里的蒸馏 / 审核 / 推送，页面的「提案」页，流程图后三格，定时触发。

模型、git、`~/.claude`、知识库目录全是替身 / tmp。
"""
from __future__ import annotations

import datetime as dt
import json
import os
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
from pet.config import Config

app = QApplication.instance() or QApplication([])

NOW = dt.datetime(2026, 10, 31, 21, 35)
RAW = json.dumps([
    {"action": "add", "scope": "global", "type": "feedback", "title": "回复用中文", "why": "英语是第二语言",
     "how": "解释一律中文", "evidence": ["2026-10-30 Pet：explain in chinese from now on"]},
    {"action": "add", "scope": "project", "project": "Pet", "type": "project", "title": "候选库放本地",
     "how": "不进 git", "evidence": ["2026-10-31 Pet：同意原始库放在本地"]},
], ensure_ascii=False)


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


class _Host:
    def __init__(self) -> None:
        self.bubbles: list[str] = []
        self.sprite = None

    def show_bubble(self, text: str, _ms: int) -> None:
        self.bubbles.append(text)

    def open_settings_for(self, _s) -> None:
        pass


def _transcript(home, *texts: str) -> None:
    folder = home / ".claude" / "projects" / "C--Users-me-Github-Pet"
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, text in enumerate(texts, 1):
        rows.append(json.dumps({"type": "user", "isSidechain": False, "uuid": f"u{n}", "sessionId": "s",
                                "timestamp": f"2026-10-31T1{n}:00:00Z", "cwd": r"C:\Users\me\Github\Pet",
                                "entrypoint": "cli", "gitBranch": "main", "message": {"role": "user", "content": text}},
                               ensure_ascii=False))
    (folder / "s1.jsonl").write_text("".join(r + "\n" for r in rows), encoding="utf-8")


class _Fakes:
    def __init__(self, text: str = RAW, *, fail: bool = False, git_ok: bool = True) -> None:
        self.text, self.fail, self.git_ok = text, fail, git_ok
        self.prompts: list[str] = []
        self.git_calls: list[list[str]] = []

    def complete(self, prompt, system, provider, *, model="", effort="", timeout=None):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("quota")
        return SimpleNamespace(text=self.text, model=model or provider.model, input_tokens=2000, output_tokens=400)

    def git(self, repo_dir, args, **_kw):
        self.git_calls.append(list(args))
        if args[:3] == ["diff", "--cached", "--quiet"]:
            return 1, ""
        return (0, "") if self.git_ok else (1, "remote: denied")


def _service(tmp_path, fakes: _Fakes, *, enabled: bool = True, now=None):
    config = Config(tmp_path / "appdata")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "CLAUDE.md").write_text("## mine\n- keep\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    config.set(md.CONFIG_KEY, {**md.normalize(None), "enabled": enabled, "daily_at": "21:30"})
    config.set("personal", {"repo_dir": str(vault)})
    _transcript(home, "以后回复都用中文", "同意原始库放在本地")
    clock = {"now": now or NOW}
    service = svc.MemoryDistillService(
        config, spawn=lambda target: target(), roots=[home / ".claude" / "projects"], home=home,
        wsl_runner=lambda *a, **k: (1, ""), opener=lambda target: True, complete=fakes.complete,
        provider=SimpleNamespace(model="claude-sonnet-5-5", effort="high"), token=lambda: "", git=fakes.git,
        now=lambda: clock["now"])
    service._clock = clock
    service.refresh_now()
    return service, home, vault


# ---------------------------------------------------------------- 服务


def test_distill_now_sends_personal_candidates_and_stores_pending_proposals(tmp_path):
    fakes = _Fakes()
    service, home, _ = _service(tmp_path, fakes)
    results = []
    service.distilled.connect(lambda result, manual: results.append((result, manual)))
    assert service.distill_now() is True
    result, manual = results[0]
    assert manual and result.ok and result.candidates == 2 and result.proposals == 2 and result.added == 2
    assert result.model == "claude-sonnet-5-5" and result.tokens_in == 2000
    assert "以后回复都用中文" in fakes.prompts[0] and "## mine" in fakes.prompts[0], "候选和现有 CLAUDE.md 都在提示词里"
    assert [p.title for p in service.proposals().pending()] == ["回复用中文", "候选库放本地"]
    state = service.distill_state()
    assert state["done_date"] == "2026-10-31" and state["last_result"]["added"] == 2
    stats = service.stats()
    assert stats["proposals"]["pending"] == 2 and stats["distill"]["last_run_at"].startswith("2026-10-31T21:35")
    assert service.distill_now() and results[-1][0].candidates == 0, "第二次没新候选，不调模型"
    assert len(fakes.prompts) == 1


def test_distill_failure_is_reported_and_retried_later(tmp_path):
    fakes = _Fakes(fail=True)
    service, _, _ = _service(tmp_path, fakes)
    results = []
    service.distilled.connect(lambda result, manual: results.append(result))
    service.distill_now()
    assert not results[0].ok and results[0].error == "quota" and not service.distilling
    assert service.distill_state()["attempts"] == 1 and "done_date" not in service.distill_state()
    assert "quota" in service.stats()["distill"]["last_error"]


def test_check_runs_the_daily_distill_once_after_the_configured_time(tmp_path):
    fakes = _Fakes()
    service, _, _ = _service(tmp_path, fakes, now=NOW.replace(hour=20))
    service.check()
    assert fakes.prompts == [], "没到点"
    service._clock["now"] = NOW
    service.check()
    assert len(fakes.prompts) == 1
    service.check()
    assert len(fakes.prompts) == 1, "今天做过了"
    service._config.set(md.CONFIG_KEY, {**md.normalize(None), "enabled": False})
    service._clock["now"] = NOW + dt.timedelta(days=1)
    service.check()
    assert len(fakes.prompts) == 1, "关着不自动蒸馏"


def test_review_accept_writes_claude_md_project_memory_and_vault_then_pushes(tmp_path):
    fakes = _Fakes()
    service, home, vault = _service(tmp_path, fakes)
    service.distill_now()
    first, second = service.proposals().pending()
    synced = []
    service.synced.connect(lambda ok, reason: synced.append((ok, reason)))
    applied = service.review(first.id, run.STATUS_ACCEPTED, title="回复一律中文", why="英语是第二语言", how="解释用中文")
    assert applied.claude_md and applied.vault_written and applied.error == ""
    text = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("## mine\n- keep\n\n" + sink.BLOCK_START) and "- **回复一律中文** — 解释用中文" in text, "改过的标题生效，块外原样"
    assert (vault / "User" / "Claude Memory.md").exists()
    assert synced == [(True, "")] and fakes.git_calls[-1] == ["push", "-q"] and service.sync_state == "pushed"
    assert list((service.root / "backups").glob("CLAUDE.md.*.bak"))
    applied = service.review(second.id, run.STATUS_ACCEPTED)
    memory = home / ".claude" / "projects" / "C--Users-me-Github-Pet" / "memory"
    assert applied.project_file == str(memory / f"distill-{second.id}.md") and (memory / "MEMORY.md").exists()
    assert "候选库放本地" in (memory / "MEMORY.md").read_text(encoding="utf-8")
    assert service.proposals().pending() == [] and service.proposals().counts()["accepted"] == 2
    assert service.stats()["entries"] == {"global": 1, "project": 1, "retired": 0}


def test_review_reject_goes_on_the_never_again_list_and_skip_does_not(tmp_path):
    fakes = _Fakes()
    service, home, _ = _service(tmp_path, fakes)
    service.distill_now()
    first, second = service.proposals().pending()
    assert service.review(first.id, run.STATUS_REJECTED) is None
    assert service.review(second.id, run.STATUS_SKIPPED) is None
    assert service.proposals().dismissed_titles() == ["回复用中文"]
    assert sink.BLOCK_START not in (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert service.review("nope", run.STATUS_ACCEPTED) is None and service.review(first.id, "bogus") is None


def test_vault_push_failure_keeps_the_file_and_reports(tmp_path):
    fakes = _Fakes(git_ok=False)
    service, _, vault = _service(tmp_path, fakes)
    service.distill_now()
    first = service.proposals().pending()[0]
    service.review(first.id, run.STATUS_ACCEPTED)
    assert service.sync_state == "failed" and "denied" in service.sync_error
    assert (vault / "User" / "Claude Memory.md").exists()
    assert service.stats()["vault"]["state"] == "failed"


def test_distill_without_a_provider_fails_softly(tmp_path):
    config = Config(tmp_path / "appdata")
    service = svc.MemoryDistillService(config, spawn=lambda target: target(), roots=[tmp_path / "none"],
                                       home=tmp_path / "home", wsl_runner=lambda *a, **k: (1, ""),
                                       provider=None, complete=lambda *a, **k: None, now=lambda: NOW)

    def boom(_config):
        raise RuntimeError("no chat module")

    import pet.personal_service as ps
    original = ps.resolve_chat_provider
    ps.resolve_chat_provider = boom
    try:
        results = []
        service.distilled.connect(lambda result, manual: results.append(result))
        assert service.distill_now() is False
        assert results and results[0].error == "no chat module" and not service.distilling
    finally:
        ps.resolve_chat_provider = original


# ---------------------------------------------------------------- 页面


def test_proposals_tab_lists_edits_and_reviews(tmp_path):
    fakes = _Fakes()
    service, home, _ = _service(tmp_path, fakes)
    host = _Host()
    controller = ui.MemoryDistillController(host, service)
    controller.open_window()
    window = controller.window
    try:
        assert window.tabs.tabText(2) == "提案" and window.proposal_list.count() == 0
        assert not window.accept_btn.isEnabled() and "没有待审" in window.proposal_head.text()
        window.distill_btn.click()
        assert window.tabs.currentIndex() == 2, "手动总结出了提案就切到提案页"
        assert window.tabs.tabText(2) == "提案 2" and window.proposal_list.count() == 2
        assert window.proposal_list.item(0).text() == "新增 · 全局 · 回复用中文"
        assert window.proposal_list.item(1).text() == "新增 · Pet · 候选库放本地"
        assert window.status_label.text() == "总结完成：2 条候选 → 2 条提案，新增 2 条待审"
        assert window.run_label.text().startswith("上次总结 2026-10-31 21:35 · claude-sonnet-5-5 · high · 2,000 → 400 tokens")
        assert "上次 10-31 21:35 · 2 条提案" == window.diagram.value("distill")
        assert window.diagram.value("review") == "待审 2 · 已接受 0 · 已拒 0"
        window.proposal_list.setCurrentRow(0)
        assert window.title_edit.text() == "回复用中文" and window.why_edit.toPlainText() == "英语是第二语言"
        assert "explain in chinese from now on" in window.evidence_label.text()
        assert window.proposal_head.text().startswith("新增 · 全局 · feedback · 提于 10-31 21:35")
        window.title_edit.setText("回复一律中文")
        window.accept_btn.click()
        assert "已写入：全局 CLAUDE.md 受管块、AI-Base" in window.review_status.text()
        assert "- **回复一律中文**" in (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        assert window.proposal_list.count() == 1 and window.tabs.tabText(2) == "提案 1"
        assert window.diagram.value("review") == "待审 1 · 已接受 1 · 已拒 0"
        assert window.diagram.value("sink") == "全局 1 条 · 项目 0 条"
        window.reject_btn.click()
        assert window.proposal_list.count() == 0 and window.review_status.text() == "记下了。"
        assert window.tabs.tabText(2) == "提案" and not window.accept_btn.isEnabled()
        assert host.bubbles == [], "手动总结不弹气泡"
    finally:
        window.close()
        window.deleteLater()


def test_scheduled_run_bubbles_and_review_tile_opens_the_tab(tmp_path):
    fakes = _Fakes()
    service, _, _ = _service(tmp_path, fakes)
    host = _Host()
    controller = ui.MemoryDistillController(host, service)
    controller.open_window()
    window = controller.window
    try:
        service.distill_now(manual=False)
        assert host.bubbles == ["会话记忆蒸馏整理出 2 条待审，到流程页「提案」里看看"]
        window.tabs.setCurrentIndex(0)
        window._on_stage("review")
        assert window.tabs.currentIndex() == 2
    finally:
        window.close()
        window.deleteLater()


def test_settings_mirror_toggle_round_trips(tmp_path):
    from PySide6.QtWidgets import QWidget

    from pet import settings_memory_distill as sd

    config = Config(tmp_path / "appdata")
    dialog = QWidget()
    dialog.config = config
    rows = sd.distill_rows(dialog)      # 行对象持有控件，得留着
    assert rows and dialog.distill_mirror_check.isChecked(), "默认镜像"
    dialog.distill_mirror_check.setChecked(False)
    sd.save_distill_settings(dialog)
    assert config.get(md.CONFIG_KEY)["mirror_to_vault"] is False
    dialog.deleteLater()
