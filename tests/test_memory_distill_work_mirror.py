# -*- coding: utf-8 -*-
"""会话记忆蒸馏·第三期（公司侧）——镜像：接受了的公司侧条目同时写进公司侧知识库副本（AI-Base-Memory），
git 经 WSL 提交推送；不进个人知识库。

WSL（文件系统、``claude -p``、git）是替身；知识库副本是 tmp_path 里的真目录。
"""
from __future__ import annotations

import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from pet import i18n
from pet import memory_distill as md
from pet import memory_distill_run as run
from pet import memory_distill_sink as sink
from pet import memory_distill_ui as ui
from pet import memory_distill_wsl_sink as wsink
from pet import work_notes as wn
from pet.config import Config

from tests.test_memory_distill_work_sink import CLAUDE_MD, NOW, ORIGINAL, _Host, _proposal, _service, _Wsl, _WslFs

app = QApplication.instance() or QApplication([])
NOTE = "memory/Claude Memory.md"


@pytest.fixture(autouse=True)
def _chinese_again():
    yield
    i18n.set_language("zh")


class _WslGit(_Wsl):
    """再多认一条：在 WSL 里跑的 git 同步命令。"""

    def __init__(self, files=None, *, git_out: tuple[int, str] = (0, "")) -> None:
        super().__init__(files)
        self.git: list[str] = []
        self.git_out = git_out

    def __call__(self, args, *, input_text=None, timeout=30.0):
        if args[:3] == ["-e", "bash", "-lc"] and "git add" in args[3]:
            self.git.append(args[3])
            return self.git_out
        return super().__call__(args, input_text=input_text, timeout=timeout)


# ---------------------------------------------------------------- git 命令


def test_sync_command_can_be_limited_to_other_paths():
    default = wn.sync_command(r"C:\Users\me\WorkSpace\AI-Base-Memory", "note: x")
    assert "git add -A -- 'note' 'slack' '.obsidian'" in default, "工作笔记那条不变"
    only = wn.sync_command(r"C:\Users\me\WorkSpace\AI-Base-Memory", "claude memory: x", paths=("memory",))
    assert only == ("cd '/mnt/c/Users/me/WorkSpace/AI-Base-Memory' && git add -A -- 'memory'"
                    " && (git diff --cached --quiet || git commit -q -m 'claude memory: x')"
                    " && git pull -q --rebase && git push -q")


# ---------------------------------------------------------------- 落盘时写镜像


def test_accepted_work_entries_are_rendered_into_the_work_vault_note(tmp_path):
    vault = tmp_path / "AI-Base-Memory"
    vault.mkdir()
    fs = _WslFs({CLAUDE_MD: ORIGINAL})
    entries = sink.EntriesStore(tmp_path, md.SIDE_WORK)
    kwargs = {"entries": entries, "runner": fs, "backup_dir": tmp_path / "backups", "vault_dir": vault}
    first = wsink.apply_proposal(_proposal("add", "global", "文档按模板写"), NOW, **kwargs)
    second = wsink.apply_proposal(_proposal("add", "project", "接口先别动", project="/home/me/corp"), NOW, **kwargs)
    assert first.vault_written and second.vault_written
    text = (vault / NOTE).read_text(encoding="utf-8")
    assert "# Claude Memory" in text and "## 全局" in text and "- **文档按模板写** — 照做" in text
    assert "## 项目 `/home/me/corp`" in text and "- **接口先别动** — 照做" in text
    assert "WSL" in text.split("## 全局")[0], "这篇写明条目落在 WSL 里的 ~/.claude"
    assert "\r" not in (vault / NOTE).read_bytes().decode("utf-8")
    off = wsink.apply_proposal(_proposal("add", "global", "不镜像的"), NOW, **{**kwargs, "mirror": False})
    assert not off.vault_written and "不镜像的" not in (vault / NOTE).read_text(encoding="utf-8")
    gone = wsink.apply_proposal(_proposal("add", "global", "没有副本"), NOW, **{**kwargs, "vault_dir": tmp_path / "nope"})
    assert gone.error == "" and not gone.vault_written, "没有知识库副本不算失败"


def test_a_failed_wsl_write_does_not_touch_the_vault(tmp_path):
    vault = tmp_path / "AI-Base-Memory"
    vault.mkdir()
    fs = _WslFs({CLAUDE_MD: ORIGINAL})
    fs.fail_writes = True
    applied = wsink.apply_proposal(_proposal("add", "global", "文档按模板写"), NOW,
                                   entries=sink.EntriesStore(tmp_path, md.SIDE_WORK), runner=fs,
                                   backup_dir=tmp_path / "backups", vault_dir=vault)
    assert applied.error and not applied.vault_written and not (vault / NOTE).exists()


# ---------------------------------------------------------------- 服务与页面


def _with_vault(tmp_path, runner, *, mirror: bool = True):
    service, home, personal_vault = _service(tmp_path, runner)
    work_vault = tmp_path / "AI-Base-Memory"
    work_vault.mkdir()
    service._config.set(wn.CONFIG_KEY, {"repo_dir": str(work_vault)})
    service._config.set(md.CONFIG_KEY, {**service.settings(), "work_mirror_to_vault": mirror})
    return service, personal_vault, work_vault


def test_accepting_mirrors_to_the_work_vault_and_pushes_through_wsl_only(tmp_path):
    runner = _WslGit({CLAUDE_MD: ORIGINAL})
    service, personal_vault, work_vault = _with_vault(tmp_path, runner)
    service.distill_now(side=md.SIDE_WORK)
    first = service.proposals().pending()[0]
    synced: list = []
    service.synced.connect(lambda ok, reason: synced.append((ok, reason)))
    service.review(first.id, run.STATUS_ACCEPTED)
    assert "- **文档按模板写**" in (work_vault / NOTE).read_text(encoding="utf-8")
    assert len(runner.git) == 1 and "git add -A -- 'memory'" in runner.git[0], "只提交 memory/，不带别人没提交的改动"
    assert f"claude memory: {NOW:%Y-%m-%d %H:%M}" in runner.git[0] and "git push -q" in runner.git[0]
    assert "文档按模板写" not in runner.git[0], "提交说明里不写条目内容"
    assert synced == [(True, "")] and service.stats()["vault_work"]["state"] == "pushed"
    assert list(personal_vault.iterdir()) == [] and service._git_calls == [], "个人知识库和个人仓库的 git 不碰"
    assert service.stats()["vault"]["state"] == ""


def test_push_failure_keeps_the_note_and_is_reported(tmp_path):
    runner = _WslGit({CLAUDE_MD: ORIGINAL}, git_out=(1, "remote: rejected by hook"))
    service, _personal_vault, work_vault = _with_vault(tmp_path, runner)
    controller = ui.MemoryDistillController(_Host(), service)
    controller.open_window()
    window = controller.window
    try:
        window.distill_work_btn.click()
        window.proposal_list.setCurrentRow(0)
        window.accept_btn.click()
        assert (work_vault / NOTE).exists() and service.proposals().counts()["accepted"] == 1, "条目已经落了，只是没推上去"
        assert service.stats()["vault_work"]["state"] == "failed"
        assert "rejected by hook" in window.review_status.text()
        assert window.diagram.value("sink").endswith("推送失败")
    finally:
        window.close()
        window.deleteLater()


def test_review_status_names_the_work_vault(tmp_path):
    runner = _WslGit({CLAUDE_MD: ORIGINAL})
    service, _personal_vault, _work_vault = _with_vault(tmp_path, runner)
    controller = ui.MemoryDistillController(_Host(), service)
    controller.open_window()
    window = controller.window
    try:
        window.distill_work_btn.click()
        window.proposal_list.setCurrentRow(0)
        window.accept_btn.click()
        assert window.review_status.text() == "已写入：WSL 里的 CLAUDE.md 受管块、AI-Base-Memory 的 memory/Claude Memory.md（推送中）"
    finally:
        window.close()
        window.deleteLater()


def test_work_mirror_can_be_switched_off_in_settings(tmp_path):
    from pet import settings_memory_distill as sd

    runner = _WslGit({CLAUDE_MD: ORIGINAL})
    service, _personal_vault, work_vault = _with_vault(tmp_path, runner, mirror=False)
    service.distill_now(side=md.SIDE_WORK)
    service.review(service.proposals().pending()[0].id, run.STATUS_ACCEPTED)
    assert not (work_vault / NOTE).exists() and runner.git == []
    assert md.normalize(None)["work_mirror_to_vault"] is True
    config = Config(tmp_path / "appdata2")
    dialog = QWidget()
    dialog.config = config
    rows = sd.distill_rows(dialog)
    assert "settingRow_distill_work_mirror" in [row.objectName() for row in rows]
    assert dialog.distill_work_mirror_check.isChecked()
    dialog.distill_work_mirror_check.setChecked(False)
    sd.save_distill_settings(dialog)
    assert config.get(md.CONFIG_KEY)["work_mirror_to_vault"] is False
    dialog.deleteLater()


def test_generated_at_is_stamped(tmp_path):
    text = sink.render_vault_note([], dt.datetime(2026, 11, 10, 9, 5), intro="x")
    assert "updated: 2026-11-10 09:05" in text and "x" in text
